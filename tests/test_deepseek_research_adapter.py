from __future__ import annotations

import json
import sys
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ctrl_v2.application.structured_contracts import PdfLocator, XlsxLocator
from ctrl_v2.domain.enums import EvidenceAuthorityLevel, EvidenceSourceType
from ctrl_v2.evaluation.deepseek_chat import (
    DEFAULT_MODEL,
    OFFICIAL_BASE_URL,
    OFFICIAL_CHAT_COMPLETIONS_ENDPOINT,
    DeepSeekChatResearchAdapter,
    DeepSeekConfigurationError,
    DeepSeekDataPolicyError,
    DeepSeekEmptyOutputError,
    DeepSeekInvalidJSONError,
    DeepSeekProviderCallError,
    DeepSeekResearchConfig,
    DeepSeekSchemaViolationError,
    DeepSeekUnexpectedToolCallError,
)
from ctrl_v2.evaluation.deepseek_llm_smoke import main as deepseek_smoke_main
from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicExtractionOutput,
    AtomicRequirement,
    DataClassification,
    EvidenceVerificationOutput,
    EvidenceVerificationRequest,
    MappingDisposition,
    ProductVersionCandidate,
    QuantitativeComparator,
    QuantitativeConstraint,
    RawRequirement,
    RequirementMappingCandidate,
    RequirementModality,
    VerificationLabel,
    VerificationReasonTag,
)
from ctrl_v2.evaluation.product_intelligence import (
    apply_evidence_guardrails,
    validate_extraction,
)
from ctrl_v2.evaluation.retrieval_contracts import (
    EvidenceSpanCandidate,
    EvidenceSpanProvenance,
    RetrievedEvidenceSpan,
)


class FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.completions = FakeCompletions(responses)
        self.chat = SimpleNamespace(completions=self.completions)


def _raw(
    classification: DataClassification = DataClassification.SYNTHETIC_SAFE,
) -> RawRequirement:
    text = "The public demo service must support SAML 2.0."
    return RawRequirement(
        requirement_id="deepseek-public-case",
        original_text=text,
        source_locator=XlsxLocator(sheet="Public", cell_range="A1"),
        data_classification=classification,
    )


def _extraction_output(*, normalized_text: str | None = None) -> AtomicExtractionOutput:
    source = _raw()
    return AtomicExtractionOutput(
        requirements=(
            AtomicRequirement(
                atomic_id="REQ-SAML",
                normalized_text=normalized_text or source.original_text,
                original_source_text=source.original_text,
                source_quote=source.original_text,
                source_start_offset=0,
                source_end_offset=len(source.original_text),
                source_locator=source.source_locator,
                modality=RequirementModality.MUST,
                category="IDENTITY",
            ),
        )
    )


def _response(
    content: str | None,
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    model: str = DEFAULT_MODEL,
    finish_reason: str = "stop",
    tool_calls=(),
):
    return SimpleNamespace(
        model=model,
        choices=(
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(
                    content=content,
                    reasoning_content="hidden reasoning must be ignored",
                    tool_calls=tool_calls,
                ),
            ),
        ),
        usage=SimpleNamespace(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
    )


def _adapter(
    responses: list[object],
    config: DeepSeekResearchConfig | None = None,
    *,
    timer=None,
) -> tuple[DeepSeekChatResearchAdapter, FakeClient]:
    client = FakeClient(responses)
    kwargs = {"client": client}
    if timer is not None:
        kwargs["timer"] = timer
    return DeepSeekChatResearchAdapter(config, **kwargs), client


def _verification_request(
    *,
    source_type: EvidenceSourceType = EvidenceSourceType.OFFICIAL_SPECIFICATION,
) -> EvidenceVerificationRequest:
    source_text = "The product must support at least 10,000 concurrent users."
    atomic = AtomicRequirement(
        atomic_id="REQ-CONCURRENT",
        normalized_text=source_text,
        original_source_text=source_text,
        source_quote=source_text,
        source_start_offset=0,
        source_end_offset=len(source_text),
        source_locator=XlsxLocator(sheet="Public", cell_range="A2"),
        modality=RequirementModality.MUST,
        category="SCALABILITY",
        quantitative_constraint=QuantitativeConstraint(
            comparator=QuantitativeComparator.GREATER_THAN_OR_EQUAL,
            value="10,000",
            unit="concurrent users",
        ),
    )
    mapping = RequirementMappingCandidate(
        requirement_id=atomic.atomic_id,
        disposition=MappingDisposition.MATCH,
        product_id="product",
        product_version_id="product-7",
        capability_id="scale.concurrent-users",
        score=1.0,
        explanation="controlled mapping",
    )
    evidence = RetrievedEvidenceSpan(
        candidate=EvidenceSpanCandidate(
            evidence_span_id="SPAN-REGISTERED",
            canonical_text="Product 7 supports 10,000 registered users.",
            provenance=EvidenceSpanProvenance(
                asset_path="public/product-7-spec.pdf",
                document_key="product-spec",
                document_version="2026.1",
                source_sha256="a" * 64,
                locator=PdfLocator(page=4),
                source_type=source_type,
                authority_level=EvidenceAuthorityLevel.AUTHORITATIVE,
                valid_from=date(2026, 1, 1),
                product_version_key="product-7",
            ),
        ),
        rank=1,
        score=1.0,
        method="test",
    )
    return EvidenceVerificationRequest(
        requirement=atomic,
        mapping=mapping,
        evidence=evidence,
        product_version=ProductVersionCandidate(
            product_version_id="product-7",
            product_id="product",
            version_label="7.0",
            valid_from=date(2026, 1, 1),
        ),
        assessment_as_of=date(2026, 8, 21),
        data_classification=DataClassification.SYNTHETIC_SAFE,
    )


def test_official_endpoint_model_and_explicit_thinking_configuration():
    timer_values = iter((10.0, 10.2))
    adapter, client = _adapter(
        [_response(_extraction_output().model_dump_json())],
        DeepSeekResearchConfig(
            thinking_enabled=True,
            reasoning_effort="high",
            timeout_seconds=42.0,
            max_output_tokens=2048,
            max_retries=1,
        ),
        timer=lambda: next(timer_values),
    )

    result = adapter.extract(_raw())

    call = client.completions.calls[0]
    assert OFFICIAL_BASE_URL == "https://api.deepseek.com"
    assert OFFICIAL_CHAT_COMPLETIONS_ENDPOINT == (
        "https://api.deepseek.com/chat/completions"
    )
    assert call["model"] == "deepseek-v4-pro"
    assert call["response_format"] == {"type": "json_object"}
    assert call["extra_body"] == {"thinking": {"type": "enabled"}}
    assert call["reasoning_effort"] == "high"
    assert call["max_tokens"] == 2048
    assert call["timeout"] == 42.0
    assert call["tools"] == []
    assert "tool_choice" not in call
    assert call["stream"] is False
    assert "Expected JSON Schema" in call["messages"][0]["content"]
    record = result.model_call
    assert record is not None
    assert record.provider == "deepseek"
    assert record.model_id == "deepseek-v4-pro"
    assert record.prompt_version == "atomic-requirement-extraction-deepseek-v1"
    assert record.latency_ms == pytest.approx(200.0)
    assert record.provider_configuration is not None
    assert record.provider_configuration.base_url == OFFICIAL_BASE_URL
    assert (
        record.provider_configuration.endpoint_url == OFFICIAL_CHAT_COMPLETIONS_ENDPOINT
    )
    assert record.provider_configuration.transport_max_retries == 0
    assert record.provider_configuration.output_max_retries == 1


def test_unofficial_base_urls_and_legacy_models_are_not_configurable():
    assert DeepSeekResearchConfig().reasoning_effort == "high"
    with pytest.raises(ValidationError):
        DeepSeekResearchConfig(model_id="deepseek-chat")
    with pytest.raises(ValidationError):
        DeepSeekResearchConfig(base_url="https://unofficial.example")


def test_disabled_thinking_is_explicit_and_sends_no_reasoning_effort():
    adapter, client = _adapter(
        [_response(_extraction_output().model_dump_json())],
        DeepSeekResearchConfig(thinking_enabled=False),
    )

    result = adapter.extract(_raw())

    call = client.completions.calls[0]
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in call
    assert result.model_call is not None
    assert result.model_call.reasoning_effort == "disabled"


def test_api_key_is_read_only_from_required_environment_variable(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-deepseek-key")
    captured: dict = {}
    client = FakeClient([_response(_extraction_output().model_dump_json())])

    def factory(**kwargs):
        captured.update(kwargs)
        return client

    adapter = DeepSeekChatResearchAdapter(client_factory=factory)
    adapter.extract(_raw())

    assert captured == {
        "api_key": "test-only-deepseek-key",
        "base_url": OFFICIAL_BASE_URL,
        "timeout": 60.0,
        "max_retries": 0,
    }
    assert "api_key" not in DeepSeekResearchConfig.model_fields
    assert "test-only-deepseek-key" not in repr(adapter.config)


def test_missing_key_fails_before_sdk_initialization(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    with pytest.raises(DeepSeekConfigurationError) as caught:
        DeepSeekChatResearchAdapter()

    assert caught.value.failure_reason == "DEEPSEEK_API_KEY_MISSING"


@pytest.mark.parametrize(
    "classification",
    [
        DataClassification.CONFIDENTIAL,
        DataClassification.RESTRICTED,
        DataClassification.PERSONAL_DATA,
        DataClassification.CUSTOMER_CONFIDENTIAL,
    ],
)
def test_prohibited_data_is_blocked_before_serialization_or_network(classification):
    adapter, client = _adapter([_response(_extraction_output().model_dump_json())])

    with pytest.raises(DeepSeekDataPolicyError) as caught:
        adapter.extract(_raw(classification))

    assert caught.value.failure_reason == f"DATA_CLASSIFICATION_BLOCKED:{classification.value}"
    assert client.completions.calls == []


def test_configuration_cannot_allow_prohibited_classification():
    with pytest.raises(ValidationError, match="only public/demo/synthetic"):
        DeepSeekResearchConfig(
            allowed_data_classifications=(DataClassification.CUSTOMER_CONFIDENTIAL,)
        )


def test_empty_output_retries_once_and_accumulates_usage_and_failure_metadata():
    adapter, client = _adapter(
        [
            _response("", input_tokens=4, output_tokens=1),
            _response(_extraction_output().model_dump_json(), input_tokens=6, output_tokens=3),
        ],
        DeepSeekResearchConfig(max_retries=1),
    )

    result = adapter.extract(_raw())

    assert len(client.completions.calls) == 2
    assert result.model_call is not None
    assert result.model_call.retry_count == 1
    assert result.model_call.failure_reasons == ("EMPTY_OUTPUT",)
    assert result.model_call.token_usage.input_tokens == 10
    assert result.model_call.token_usage.output_tokens == 4
    assert result.model_call.token_usage.total_tokens == 14


def test_invalid_json_has_bounded_retry_and_typed_final_failure():
    adapter, client = _adapter(
        [_response("not-json"), _response("still-not-json")],
        DeepSeekResearchConfig(max_retries=1),
    )

    with pytest.raises(DeepSeekInvalidJSONError) as caught:
        adapter.extract(_raw())

    assert len(client.completions.calls) == 2
    assert caught.value.retry_count == 1
    assert caught.value.failure_reasons == ("INVALID_JSON", "INVALID_JSON")


def test_empty_output_exhaustion_is_typed():
    adapter, client = _adapter(
        [_response(None), _response("   ")],
        DeepSeekResearchConfig(max_retries=1),
    )

    with pytest.raises(DeepSeekEmptyOutputError) as caught:
        adapter.extract(_raw())

    assert len(client.completions.calls) == 2
    assert caught.value.failure_reason == "EMPTY_OUTPUT"


def test_valid_json_that_violates_schema_fails_without_retry_or_repair():
    adapter, client = _adapter(
        [_response('{"schema_version":"1.0","requirements":[{"invented":true}]}')],
        DeepSeekResearchConfig(max_retries=3),
    )

    with pytest.raises(DeepSeekSchemaViolationError) as caught:
        adapter.extract(_raw())

    assert len(client.completions.calls) == 1
    assert caught.value.retry_count == 0
    assert caught.value.failure_reason == "SCHEMA_INVALID"


def test_tool_call_output_is_rejected_even_if_content_contains_json():
    adapter, client = _adapter(
        [
            _response(
                _extraction_output().model_dump_json(),
                tool_calls=(SimpleNamespace(id="call-1"),),
            )
        ]
    )

    with pytest.raises(DeepSeekUnexpectedToolCallError):
        adapter.extract(_raw())

    assert len(client.completions.calls) == 1


def test_invented_numeric_constraint_is_blocked_by_existing_validator():
    source_text = "The service must support at least 10,000 concurrent users."
    raw = RawRequirement(
        requirement_id="numeric-case",
        original_text=source_text,
        source_locator=XlsxLocator(sheet="Public", cell_range="A3"),
        data_classification=DataClassification.SYNTHETIC_SAFE,
    )
    invented = AtomicExtractionOutput(
        requirements=(
            AtomicRequirement(
                atomic_id="REQ-USERS",
                normalized_text="The service must support at least 20,000 concurrent users.",
                original_source_text=source_text,
                source_quote=source_text,
                source_start_offset=0,
                source_end_offset=len(source_text),
                source_locator=raw.source_locator,
                modality=RequirementModality.MUST,
                category="SCALABILITY",
            ),
        )
    )
    adapter, _ = _adapter([_response(invented.model_dump_json())])

    provider_result = adapter.extract(raw)
    validation = validate_extraction(raw, provider_result.output.requirements)

    assert validation.accepted == ()
    assert validation.rejected[0].atomic_id == "REQ-USERS"


@pytest.mark.parametrize(
    ("source_type", "expected_tag"),
    [
        (EvidenceSourceType.OFFICIAL_SPECIFICATION, VerificationReasonTag.WRONG_METRIC),
        (EvidenceSourceType.ROADMAP, VerificationReasonTag.ROADMAP_ONLY),
    ],
)
def test_provider_entails_cannot_bypass_existing_metric_or_roadmap_guardrails(
    source_type,
    expected_tag,
):
    provider_output = EvidenceVerificationOutput(
        label=VerificationLabel.ENTAILS,
        explanation="Provider proposed entailment.",
    )
    adapter, _ = _adapter([_response(provider_output.model_dump_json())])
    request = _verification_request(source_type=source_type)

    output, record = adapter.verify(request)
    guarded = apply_evidence_guardrails(request, output, record)

    assert guarded.provider_output.label == VerificationLabel.ENTAILS
    assert guarded.effective_output.label == VerificationLabel.INSUFFICIENT
    assert expected_tag in guarded.effective_output.reason_tags
    assert guarded.model_call is not None
    assert guarded.model_call.provider == "deepseek"


def test_api_failure_is_typed_and_cannot_produce_extraction_or_decision():
    adapter, client = _adapter([TimeoutError("test timeout")])

    with pytest.raises(DeepSeekProviderCallError) as caught:
        adapter.extract(_raw())

    assert caught.value.failure_reason == "API_FAILURE"
    assert caught.value.__cause__ is None
    assert len(client.completions.calls) == 1


def test_adapter_never_logs_key_payload_or_reasoning(caplog, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-secret")
    adapter, _ = _adapter([_response(_extraction_output().model_dump_json())])

    result = adapter.extract(_raw())

    assert "deepseek-test-secret" not in caplog.text
    assert _raw().original_text not in caplog.text
    assert "hidden reasoning" not in caplog.text
    assert "hidden reasoning" not in result.model_dump_json()


def test_real_smoke_gate_does_not_call_api_without_explicit_flag_and_key(
    monkeypatch,
    capsys,
):
    monkeypatch.delenv("CTRL_RUN_REAL_DEEPSEEK_SMOKE", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["ctrl-deepseek-smoke"])

    with pytest.raises(SystemExit) as caught:
        deepseek_smoke_main()

    report = json.loads(capsys.readouterr().out)
    assert caught.value.code == 2
    assert report["api_actually_called"] is False
    assert report["executed"] is False
