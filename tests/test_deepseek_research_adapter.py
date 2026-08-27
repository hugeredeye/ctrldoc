from __future__ import annotations

import hashlib
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
    DeepSeekTruncatedOutputError,
    DeepSeekUnexpectedToolCallError,
    canonical_payload_sha256,
)
from ctrl_v2.evaluation.deepseek_llm_smoke import (
    FAST_MAX_OUTPUT_TOKENS,
    REASONING_MAX_OUTPUT_TOKENS,
    DeepSeekSmokeMode,
    _raw_extraction,
    _smoke_config,
    _synthetic_extraction_rejection_report,
)
from ctrl_v2.evaluation.deepseek_llm_smoke import (
    main as deepseek_smoke_main,
)
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
    TokenUsage,
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


def _rejected_smoke_extraction_output() -> AtomicExtractionOutput:
    source = _raw_extraction()

    def atom(
        atomic_id: str,
        normalized_text: str,
        source_quote: str,
        *,
        quantitative_constraint: QuantitativeConstraint | None = None,
    ) -> AtomicRequirement:
        return AtomicRequirement(
            atomic_id=atomic_id,
            normalized_text=normalized_text,
            original_source_text=source.original_text,
            source_quote=source_quote,
            source_start_offset=0,
            source_end_offset=len(source_quote),
            source_locator=source.source_locator,
            modality=RequirementModality.MUST,
            category="PUBLIC_DEMO",
            quantitative_constraint=quantitative_constraint,
        )

    return AtomicExtractionOutput(
        requirements=(
            atom(
                "REQ-LDAP",
                "Система должна поддерживать LDAP.",
                "LDAP (nonexistent quote)",
            ),
            atom(
                "REQ-SAML",
                "Система должна поддерживать SAML 2.0.",
                "SAML 2.0 (nonexistent quote)",
            ),
            atom(
                "REQ-USERS",
                "Система должна поддерживать не менее 10 000 одновременных пользователей.",
                "10 000 одновременных пользователей (nonexistent quote)",
                quantitative_constraint=QuantitativeConstraint(
                    comparator=QuantitativeComparator.GREATER_THAN_OR_EQUAL,
                    value="10 000",
                    unit="одновременных пользователей",
                ),
            ),
        )
    )


def _miscounted_smoke_extraction_output() -> AtomicExtractionOutput:
    source = _raw_extraction()

    def atom(
        atomic_id: str,
        normalized_text: str,
        source_quote: str,
        provider_start: int,
        provider_end: int,
        *,
        quantitative_constraint: QuantitativeConstraint | None = None,
    ) -> AtomicRequirement:
        return AtomicRequirement(
            atomic_id=atomic_id,
            normalized_text=normalized_text,
            original_source_text=source.original_text,
            source_quote=source_quote,
            source_start_offset=provider_start,
            source_end_offset=provider_end,
            source_locator=source.source_locator,
            modality=RequirementModality.MUST,
            category="PUBLIC_DEMO",
            quantitative_constraint=quantitative_constraint,
        )

    return AtomicExtractionOutput(
        requirements=(
            atom(
                "REQ-LDAP",
                "Система должна поддерживать LDAP.",
                "Система должна поддерживать LDAP",
                0,
                29,
            ),
            atom(
                "REQ-SAML",
                "Система должна поддерживать SAML 2.0.",
                "SAML 2.0",
                33,
                41,
            ),
            atom(
                "REQ-USERS",
                "Система должна поддерживать не менее 10 000 одновременных пользователей.",
                "не менее 10 000 одновременных пользователей",
                45,
                84,
                quantitative_constraint=QuantitativeConstraint(
                    comparator=QuantitativeComparator.GREATER_THAN_OR_EQUAL,
                    value="10 000",
                    unit="одновременных пользователей",
                ),
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
    reasoning_tokens: int | None = None,
    reasoning_content: str = "hidden reasoning must be ignored",
    tool_calls=(),
):
    return SimpleNamespace(
        model=model,
        choices=(
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(
                    content=content,
                    reasoning_content=reasoning_content,
                    tool_calls=tool_calls,
                ),
            ),
        ),
        usage=SimpleNamespace(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            completion_tokens_details=SimpleNamespace(
                reasoning_tokens=reasoning_tokens
            ),
            total_tokens=input_tokens + output_tokens,
        ),
    )


def _adapter(
    responses: list[object],
    config: DeepSeekResearchConfig | None = None,
    *,
    timer=None,
    synthetic_schema_debug_input_sha256: frozenset[str] = frozenset(),
) -> tuple[DeepSeekChatResearchAdapter, FakeClient]:
    client = FakeClient(responses)
    kwargs = {
        "client": client,
        "synthetic_schema_debug_input_sha256": synthetic_schema_debug_input_sha256,
    }
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
    assert "temperature" not in call
    assert call["stream"] is False
    assert "Expected JSON Schema" in call["messages"][0]["content"]
    record = result.model_call
    assert record is not None
    assert record.provider == "deepseek"
    assert record.model_id == "deepseek-v4-pro"
    assert record.finish_reason == "stop"
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
    assert "temperature" not in call
    assert result.model_call is not None
    assert result.model_call.reasoning_effort == "disabled"


def test_fast_smoke_mode_disables_thinking_with_recorded_budget():
    config = _smoke_config(
        DeepSeekSmokeMode.FAST,
        timeout_seconds=90.0,
        retries=0,
    )
    adapter, client = _adapter([_response(_extraction_output().model_dump_json())], config)

    result = adapter.extract(_raw())

    call = client.completions.calls[0]
    assert config.max_output_tokens == FAST_MAX_OUTPUT_TOKENS
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in call
    assert call["max_tokens"] == FAST_MAX_OUTPUT_TOKENS
    assert call["temperature"] == 0.0
    assert result.model_call is not None
    assert result.model_call.provider_configuration is not None
    assert result.model_call.provider_configuration.inference_mode == "FAST"
    assert result.model_call.provider_configuration.thinking_enabled is False
    assert result.model_call.provider_configuration.temperature == 0.0
    assert result.model_call.provider_configuration.max_output_tokens == FAST_MAX_OUTPUT_TOKENS


def test_reasoning_smoke_mode_enables_high_thinking_with_larger_bounded_budget():
    config = _smoke_config(
        DeepSeekSmokeMode.REASONING,
        timeout_seconds=180.0,
        retries=0,
    )
    adapter, client = _adapter([_response(_extraction_output().model_dump_json())], config)

    result = adapter.extract(_raw())

    call = client.completions.calls[0]
    assert config.max_output_tokens == REASONING_MAX_OUTPUT_TOKENS == 8192
    assert call["extra_body"] == {"thinking": {"type": "enabled"}}
    assert call["reasoning_effort"] == "high"
    assert call["max_tokens"] == REASONING_MAX_OUTPUT_TOKENS
    assert "temperature" not in call
    assert result.model_call is not None
    assert result.model_call.provider_configuration is not None
    assert result.model_call.provider_configuration.inference_mode == "REASONING"
    assert result.model_call.provider_configuration.thinking_enabled is True
    assert result.model_call.provider_configuration.reasoning_effort == "high"
    assert result.model_call.provider_configuration.temperature is None
    assert (
        result.model_call.provider_configuration.max_output_tokens
        == REASONING_MAX_OUTPUT_TOKENS
    )


def test_thinking_mode_rejects_unsupported_temperature_configuration():
    with pytest.raises(ValidationError, match="does not support temperature"):
        DeepSeekResearchConfig(thinking_enabled=True, temperature=0.0)


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


def test_success_preserves_actual_model_finish_reason_and_reasoning_token_usage():
    adapter, _ = _adapter(
        [
            _response(
                _extraction_output().model_dump_json(),
                input_tokens=21,
                output_tokens=34,
                reasoning_tokens=27,
                model="deepseek-v4-pro-2026-08",
            )
        ]
    )

    result = adapter.extract(_raw())

    assert result.model_call is not None
    assert result.model_call.model_id == "deepseek-v4-pro-2026-08"
    assert result.model_call.finish_reason == "stop"
    assert result.model_call.token_usage.input_tokens == 21
    assert result.model_call.token_usage.output_tokens == 34
    assert result.model_call.token_usage.reasoning_tokens == 27
    assert result.model_call.token_usage.total_tokens == 55


def test_finish_reason_length_preserves_metadata_and_remains_typed_failure():
    timer_values = iter((20.0, 20.75))
    adapter, _ = _adapter(
        [
            _response(
                _extraction_output().model_dump_json(),
                input_tokens=31,
                output_tokens=4096,
                reasoning_tokens=4001,
                model="deepseek-v4-pro-2026-08",
                finish_reason="length",
            )
        ],
        timer=lambda: next(timer_values),
    )

    with pytest.raises(DeepSeekTruncatedOutputError) as caught:
        adapter.extract(_raw())

    error = caught.value
    assert error.failure_reason == "TRUNCATED_OUTPUT"
    assert error.finish_reason == "length"
    assert error.response_model == "deepseek-v4-pro-2026-08"
    assert error.token_usage.input_tokens == 31
    assert error.token_usage.output_tokens == 4096
    assert error.token_usage.reasoning_tokens == 4001
    assert error.token_usage.total_tokens == 4127
    assert error.latency_ms == pytest.approx(750.0)
    assert error.retry_count == 0


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
    raw_output = {"schema_version": "1.0", "requirements": [{"invented": True}]}
    adapter, client = _adapter(
        [_response(json.dumps(raw_output))],
        DeepSeekResearchConfig(max_retries=3),
    )

    with pytest.raises(DeepSeekSchemaViolationError) as caught:
        adapter.extract(_raw())

    assert len(client.completions.calls) == 1
    assert caught.value.retry_count == 0
    assert caught.value.failure_reason == "SCHEMA_INVALID"
    diagnostics = caught.value.validation_diagnostics
    assert diagnostics is not None
    assert diagnostics.schema_model == "AtomicExtractionOutput"
    assert diagnostics.error_count == len(diagnostics.errors)
    assert diagnostics.error_count > 0
    assert any(issue.path == "$.requirements[0].atomic_id" for issue in diagnostics.errors)
    assert all(issue.location for issue in diagnostics.errors)
    assert all(issue.error_type for issue in diagnostics.errors)
    assert all(issue.message for issue in diagnostics.errors)
    assert diagnostics.top_level_json_keys == ("requirements", "schema_version")
    canonical = json.dumps(
        raw_output,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    assert diagnostics.canonical_output_sha256 == hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()
    assert caught.value.synthetic_output is None


def test_schema_invalid_synthetic_output_capture_requires_exclusive_safe_scope():
    with pytest.raises(
        DeepSeekConfigurationError,
        match="SYNTHETIC_OUTPUT_DEBUG_REQUIRES_EXCLUSIVE_SYNTHETIC_SAFE",
    ):
        _adapter(
            [_response("{}")],
            synthetic_schema_debug_input_sha256=frozenset({"a" * 64}),
        )


def test_schema_debug_hash_allowlist_does_not_capture_arbitrary_synthetic_payload():
    config = DeepSeekResearchConfig(
        allowed_data_classifications=(DataClassification.SYNTHETIC_SAFE,)
    )
    adapter, _ = _adapter(
        [_response('{"unexpected":"synthetic value"}')],
        config,
        synthetic_schema_debug_input_sha256=frozenset(
            {canonical_payload_sha256(_raw_extraction())}
        ),
    )

    with pytest.raises(DeepSeekSchemaViolationError) as caught:
        adapter.extract(_raw(DataClassification.SYNTHETIC_SAFE))

    assert caught.value.validation_diagnostics is not None
    assert caught.value.synthetic_output is None


@pytest.mark.parametrize(
    "classification",
    [DataClassification.CONFIDENTIAL, DataClassification.CUSTOMER_CONFIDENTIAL],
)
def test_schema_debug_scope_cannot_process_confidential_or_customer_data(classification):
    config = DeepSeekResearchConfig(
        allowed_data_classifications=(DataClassification.SYNTHETIC_SAFE,)
    )
    adapter, client = _adapter(
        [_response("{}")],
        config,
        synthetic_schema_debug_input_sha256=frozenset(
            {canonical_payload_sha256(_raw_extraction())}
        ),
    )

    with pytest.raises(DeepSeekDataPolicyError):
        adapter.extract(_raw(classification))

    assert client.completions.calls == []


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


def test_truncated_failure_never_persists_or_logs_reasoning_content(caplog):
    private_reasoning = "private chain of thought must never persist"
    adapter, _ = _adapter(
        [
            _response(
                '{"schema_version":"1.0","requirements":[]}',
                finish_reason="length",
                reasoning_tokens=4090,
                reasoning_content=private_reasoning,
            )
        ]
    )

    with pytest.raises(DeepSeekTruncatedOutputError) as caught:
        adapter.extract(_raw())

    assert private_reasoning not in caplog.text
    assert private_reasoning not in str(caught.value)
    assert private_reasoning not in repr(vars(caught.value))
    assert not hasattr(caught.value, "reasoning_content")


def test_real_smoke_gate_does_not_call_api_without_explicit_flag_and_key(
    monkeypatch,
    capsys,
):
    monkeypatch.delenv("CTRL_RUN_REAL_DEEPSEEK_SMOKE", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(sys, "argv", ["ctrl-deepseek-smoke", "--mode", "FAST"])

    with pytest.raises(SystemExit) as caught:
        deepseek_smoke_main()

    report = json.loads(capsys.readouterr().out)
    assert caught.value.code == 2
    assert report["api_actually_called"] is False
    assert report["executed"] is False
    assert report["mode"] == "FAST"
    assert report["max_output_tokens"] == FAST_MAX_OUTPUT_TOKENS


def test_reasoning_smoke_reports_truncation_diagnostics_without_real_api(
    monkeypatch,
    capsys,
):
    class TruncatedAdapter:
        def __init__(self, config, **kwargs):
            assert config.thinking_enabled is True
            assert config.reasoning_effort == "high"
            assert config.max_output_tokens == REASONING_MAX_OUTPUT_TOKENS
            assert kwargs["synthetic_schema_debug_input_sha256"] == frozenset()

        def extract(self, _raw_requirement):
            raise DeepSeekTruncatedOutputError(
                "TRUNCATED_OUTPUT",
                retry_count=0,
                latency_ms=55995.8771,
                finish_reason="length",
                response_model="deepseek-v4-pro-2026-08",
                token_usage=TokenUsage(
                    input_tokens=611,
                    output_tokens=8192,
                    reasoning_tokens=8030,
                    total_tokens=8803,
                ),
            )

    monkeypatch.setenv("CTRL_RUN_REAL_DEEPSEEK_SMOKE", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    monkeypatch.setattr(
        "ctrl_v2.evaluation.deepseek_llm_smoke.DeepSeekChatResearchAdapter",
        TruncatedAdapter,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["ctrl-deepseek-smoke", "--mode", "REASONING", "--retries", "0"],
    )

    with pytest.raises(SystemExit) as caught:
        deepseek_smoke_main()

    report = json.loads(capsys.readouterr().out)
    assert caught.value.code == 1
    assert report["mode"] == "REASONING"
    assert report["thinking"] == "enabled"
    assert report["reasoning_effort"] == "high"
    assert report["max_output_tokens"] == REASONING_MAX_OUTPUT_TOKENS
    assert report["failure_reason"] == "TRUNCATED_OUTPUT"
    assert report["finish_reason"] == "length"
    assert report["model_reported"] == "deepseek-v4-pro-2026-08"
    assert report["prompt_tokens"] == 611
    assert report["completion_tokens"] == 8192
    assert report["completion_tokens_details"]["reasoning_tokens"] == 8030
    assert report["total_tokens"] == 8803
    assert report["latency_ms"] == pytest.approx(55995.8771)
    assert report["retries"] == 0
    assert report["structured_parse_success"] is False


def test_fast_smoke_hides_schema_invalid_synthetic_output_by_default(
    monkeypatch,
    capsys,
):
    raw_output = {"schema_version": "1.0", "requirements": [{"invented": True}]}

    def adapter_factory(config, **kwargs):
        assert kwargs["synthetic_schema_debug_input_sha256"] == frozenset()
        return DeepSeekChatResearchAdapter(
            config,
            client=FakeClient([_response(json.dumps(raw_output))]),
            **kwargs,
        )

    monkeypatch.setenv("CTRL_RUN_REAL_DEEPSEEK_SMOKE", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    monkeypatch.setattr(
        "ctrl_v2.evaluation.deepseek_llm_smoke.DeepSeekChatResearchAdapter",
        adapter_factory,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["ctrl-deepseek-smoke", "--mode", "FAST", "--retries", "0"],
    )

    with pytest.raises(SystemExit) as caught:
        deepseek_smoke_main()

    report = json.loads(capsys.readouterr().out)
    assert caught.value.code == 1
    assert report["failure_reason"] == "SCHEMA_INVALID"
    assert report["schema_validation"]["schema_model"] == "AtomicExtractionOutput"
    assert "synthetic_output" not in report


def test_fast_smoke_explicitly_shows_only_builtin_synthetic_schema_output(
    monkeypatch,
    capsys,
):
    private_reasoning = "reasoning content must remain private"
    raw_output = {"schema_version": "1.0", "requirements": [{"invented": True}]}

    def adapter_factory(config, **kwargs):
        assert config.allowed_data_classifications == (DataClassification.SYNTHETIC_SAFE,)
        assert len(kwargs["synthetic_schema_debug_input_sha256"]) == 3
        return DeepSeekChatResearchAdapter(
            config,
            client=FakeClient(
                [
                    _response(
                        json.dumps(raw_output),
                        reasoning_content=private_reasoning,
                    )
                ]
            ),
            **kwargs,
        )

    monkeypatch.setenv("CTRL_RUN_REAL_DEEPSEEK_SMOKE", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    monkeypatch.setattr(
        "ctrl_v2.evaluation.deepseek_llm_smoke.DeepSeekChatResearchAdapter",
        adapter_factory,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ctrl-deepseek-smoke",
            "--mode",
            "FAST",
            "--retries",
            "0",
            "--show-synthetic-output",
        ],
    )

    with pytest.raises(SystemExit) as caught:
        deepseek_smoke_main()

    captured = capsys.readouterr().out
    report = json.loads(captured)
    assert caught.value.code == 1
    assert report["failure_reason"] == "SCHEMA_INVALID"
    assert report["synthetic_output"] == raw_output
    assert report["schema_validation"]["validation_error_count"] > 0
    assert private_reasoning not in captured
    assert private_reasoning not in json.dumps(report)


def test_fast_smoke_canonicalizes_real_miscounted_offsets_without_api_call(
    monkeypatch,
    capsys,
):
    extraction_output = _miscounted_smoke_extraction_output()
    insufficient = EvidenceVerificationOutput(
        label=VerificationLabel.INSUFFICIENT,
        explanation="Evidence does not establish the requirement",
    )

    def adapter_factory(config, **kwargs):
        assert config.thinking_enabled is False
        return DeepSeekChatResearchAdapter(
            config,
            client=FakeClient(
                [
                    _response(extraction_output.model_dump_json()),
                    _response(insufficient.model_dump_json()),
                    _response(insufficient.model_dump_json()),
                ]
            ),
            **kwargs,
        )

    monkeypatch.setenv("CTRL_RUN_REAL_DEEPSEEK_SMOKE", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    monkeypatch.setattr(
        "ctrl_v2.evaluation.deepseek_llm_smoke.DeepSeekChatResearchAdapter",
        adapter_factory,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["ctrl-deepseek-smoke", "--mode", "FAST", "--retries", "0"],
    )

    deepseek_smoke_main()

    report = json.loads(capsys.readouterr().out)
    extraction = report["extraction"]
    assert report["overall_pass"] is True
    assert extraction["accepted_atomic_ids"] == [
        "REQ-LDAP",
        "REQ-SAML",
        "REQ-USERS",
    ]
    assert extraction["conceptual_three_way_match"] is True
    assert extraction["validation_issues"] == []
    assert extraction["source_anchor_resolutions"] == [
        {
            "atomic_id": "REQ-LDAP",
            "provider_start_offset": 0,
            "provider_end_offset": 29,
            "canonical_start_offset": 0,
            "canonical_end_offset": 32,
            "exact_match_count": 1,
            "offsets_corrected": True,
        },
        {
            "atomic_id": "REQ-SAML",
            "provider_start_offset": 33,
            "provider_end_offset": 41,
            "canonical_start_offset": 35,
            "canonical_end_offset": 43,
            "exact_match_count": 1,
            "offsets_corrected": True,
        },
        {
            "atomic_id": "REQ-USERS",
            "provider_start_offset": 45,
            "provider_end_offset": 84,
            "canonical_start_offset": 46,
            "canonical_end_offset": 89,
            "exact_match_count": 1,
            "offsets_corrected": True,
        },
    ]


@pytest.mark.parametrize("show_synthetic_output", (False, True))
def test_extraction_rejection_diagnostics_require_explicit_builtin_safe_debug(
    monkeypatch,
    capsys,
    show_synthetic_output: bool,
):
    private_reasoning = "reasoning content must never be exposed"
    extraction_output = _rejected_smoke_extraction_output()
    insufficient = EvidenceVerificationOutput(
        label=VerificationLabel.INSUFFICIENT,
        explanation="Evidence does not establish the requirement",
    )

    def adapter_factory(config, **kwargs):
        expected_hash_count = 3 if show_synthetic_output else 0
        assert len(kwargs["synthetic_schema_debug_input_sha256"]) == expected_hash_count
        return DeepSeekChatResearchAdapter(
            config,
            client=FakeClient(
                [
                    _response(
                        extraction_output.model_dump_json(),
                        reasoning_content=private_reasoning,
                    ),
                    _response(
                        insufficient.model_dump_json(),
                        reasoning_content=private_reasoning,
                    ),
                    _response(
                        insufficient.model_dump_json(),
                        reasoning_content=private_reasoning,
                    ),
                ]
            ),
            **kwargs,
        )

    argv = ["ctrl-deepseek-smoke", "--mode", "FAST", "--retries", "0"]
    if show_synthetic_output:
        argv.append("--show-synthetic-output")
    monkeypatch.setenv("CTRL_RUN_REAL_DEEPSEEK_SMOKE", "true")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    monkeypatch.setattr(
        "ctrl_v2.evaluation.deepseek_llm_smoke.DeepSeekChatResearchAdapter",
        adapter_factory,
    )
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit) as caught:
        deepseek_smoke_main()

    captured = capsys.readouterr().out
    report = json.loads(captured)
    assert caught.value.code == 1
    assert report["structured_parse_success"] is True
    assert report["extraction"]["accepted_atomic_ids"] == []
    assert report["extraction"]["validation_issues"] == [
        "SOURCE_RELATION_UNRECOVERABLE",
        "SOURCE_RELATION_UNRECOVERABLE",
        "SOURCE_RELATION_UNRECOVERABLE",
    ]
    if show_synthetic_output:
        assert report["extraction"]["synthetic_output"] == extraction_output.model_dump(
            mode="json"
        )
        rejected = report["extraction"]["rejected_atoms"]
        assert [item["atomic_id"] for item in rejected] == [
            "REQ-LDAP",
            "REQ-SAML",
            "REQ-USERS",
        ]
        assert rejected[0]["source_locator"] == {
            "kind": "XLSX",
            "sheet": "PublicDemo",
            "cell_range": "A1",
            "table_name": None,
        }
        assert rejected[2]["quantitative_constraint"] == {
            "comparator": ">=",
            "value": "10 000",
            "unit": "одновременных пользователей",
        }
        assert rejected[0]["validation_issues"] == [
            {
                "code": "SOURCE_RELATION_UNRECOVERABLE",
                "message": (
                    "Source quote does not occur exactly in the declared source unit"
                ),
                "blocking": True,
            }
        ]
    else:
        assert "synthetic_output" not in report["extraction"]
        assert "rejected_atoms" not in report["extraction"]
    assert private_reasoning not in captured


def test_extraction_raw_debug_rejects_unallowlisted_and_non_synthetic_safe_inputs():
    builtin = _raw_extraction()
    output = _rejected_smoke_extraction_output()
    validation = validate_extraction(builtin, output.requirements)
    builtin_hashes = frozenset({canonical_payload_sha256(builtin)})
    arbitrary = builtin.model_copy(update={"requirement_id": "arbitrary-input"})

    assert (
        _synthetic_extraction_rejection_report(
            arbitrary,
            output,
            validation,
            allowed_input_sha256=builtin_hashes,
        )
        is None
    )
    for classification in (
        DataClassification.PUBLIC,
        DataClassification.CONFIDENTIAL,
        DataClassification.CUSTOMER_CONFIDENTIAL,
    ):
        prohibited = builtin.model_copy(update={"data_classification": classification})
        assert (
            _synthetic_extraction_rejection_report(
                prohibited,
                output,
                validation,
                allowed_input_sha256=frozenset(
                    {canonical_payload_sha256(prohibited)}
                ),
            )
            is None
        )
