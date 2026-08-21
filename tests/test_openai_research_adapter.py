from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ctrl_v2.application.structured_contracts import XlsxLocator
from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicExtractionOutput,
    AtomicRequirement,
    DataClassification,
    RawRequirement,
    RequirementModality,
)
from ctrl_v2.evaluation.openai_responses import (
    DEFAULT_MODEL,
    ESCALATION_MODEL,
    ExternalModelDataPolicyError,
    OpenAIConfigurationError,
    OpenAIProviderCallError,
    OpenAIRefusalError,
    OpenAIResearchConfig,
    OpenAIResponsesResearchAdapter,
    OpenAIStructuredOutputError,
)


class FakeResponses:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def _raw(classification: DataClassification = DataClassification.SYNTHETIC) -> RawRequirement:
    return RawRequirement(
        requirement_id="safe-public-case",
        original_text="The public demo service must support SAML 2.0.",
        source_locator=XlsxLocator(sheet="Public", cell_range="A1"),
        data_classification=classification,
    )


def _output() -> AtomicExtractionOutput:
    source = _raw()
    return AtomicExtractionOutput(
        requirements=(
            AtomicRequirement(
                atomic_id="REQ-SAML",
                normalized_text=source.original_text,
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


def _response(output_text: str | None = None, *, output=()):
    return SimpleNamespace(
        output_text=output_text,
        output=output,
        usage=SimpleNamespace(input_tokens=100, output_tokens=25, total_tokens=125),
    )


def test_default_and_explicit_escalation_models_are_configuration_only():
    assert OpenAIResearchConfig().model_id == DEFAULT_MODEL
    assert OpenAIResearchConfig(model_id=ESCALATION_MODEL).model_id == ESCALATION_MODEL


def test_real_adapter_requires_environment_key_when_no_client(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(OpenAIConfigurationError, match="OPENAI_API_KEY"):
        OpenAIResponsesResearchAdapter()


def test_confidential_or_restricted_external_calls_are_impossible():
    with pytest.raises(ValidationError, match="cannot allow confidential"):
        OpenAIResearchConfig(
            allowed_data_classifications=(DataClassification.CONFIDENTIAL,)
        )
    responses = FakeResponses(_response(_output().model_dump_json()))
    adapter = OpenAIResponsesResearchAdapter(client=FakeClient(responses))

    with pytest.raises(ExternalModelDataPolicyError, match="CONFIDENTIAL"):
        adapter.extract(_raw(DataClassification.CONFIDENTIAL))

    assert responses.calls == []


def test_responses_call_is_strict_stateless_toolless_and_reproducible():
    output = _output()
    responses = FakeResponses(_response(output.model_dump_json()))
    timer_values = iter((10.0, 10.125))
    adapter = OpenAIResponsesResearchAdapter(
        OpenAIResearchConfig(reasoning_effort="high", timeout_seconds=12.0, max_retries=1),
        client=FakeClient(responses),
        timer=lambda: next(timer_values),
    )

    result = adapter.extract(_raw())

    call = responses.calls[0]
    assert call["model"] == DEFAULT_MODEL
    assert call["store"] is False
    assert call["tools"] == []
    assert call["tool_choice"] == "none"
    assert call["timeout"] == 12.0
    assert call["reasoning"] == {"effort": "high"}
    output_format = call["text"]["format"]
    assert output_format["type"] == "json_schema"
    assert output_format["strict"] is True
    assert output_format["schema"]["additionalProperties"] is False
    assert set(output_format["schema"]["required"]) == {"schema_version", "requirements"}
    record = result.model_call
    assert record is not None
    assert record.prompt_version == "atomic-requirement-extraction-v1"
    assert record.schema_version == "1.0"
    assert record.reasoning_effort == "high"
    assert record.latency_ms == 125.0
    assert record.token_usage.total_tokens == 125
    assert record.output_sha256 == hashlib.sha256(
        json.dumps(
            output.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (_response("not-json"), OpenAIStructuredOutputError),
        (
            _response(
                "{}",
                output=(
                    SimpleNamespace(
                        type="message",
                        content=(SimpleNamespace(type="refusal"),),
                    ),
                ),
            ),
            OpenAIRefusalError,
        ),
        (
            _response("{}", output=(SimpleNamespace(type="function_call", content=()),)),
            OpenAIStructuredOutputError,
        ),
    ],
)
def test_malformed_refusal_and_tool_output_fail_typed(response, error):
    adapter = OpenAIResponsesResearchAdapter(client=FakeClient(FakeResponses(response)))

    with pytest.raises(error):
        adapter.extract(_raw())


def test_provider_failure_is_typed_without_silent_fallback():
    responses = FakeResponses(error=TimeoutError("provider timeout"))
    adapter = OpenAIResponsesResearchAdapter(client=FakeClient(responses))

    with pytest.raises(OpenAIProviderCallError) as caught:
        adapter.extract(_raw())

    assert isinstance(caught.value.__cause__, TimeoutError)


def test_adapter_does_not_log_api_key_or_source_content(caplog):
    responses = FakeResponses(_response(_output().model_dump_json()))
    adapter = OpenAIResponsesResearchAdapter(client=FakeClient(responses))

    adapter.extract(_raw())

    assert "secret" not in caplog.text
    assert _raw().original_text not in caplog.text
