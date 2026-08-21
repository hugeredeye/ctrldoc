from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from importlib import resources
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicExtractionOutput,
    AtomicExtractionResult,
    AtomicRequirementExtractor,
    DataClassification,
    EvidenceVerificationOutput,
    EvidenceVerificationRequest,
    EvidenceVerifier,
    ModelCallRecord,
    RawRequirement,
    TokenUsage,
)

DEFAULT_MODEL = "gpt-5.6-terra"
ESCALATION_MODEL = "gpt-5.6-sol"
EXTRACTION_PROMPT_VERSION = "atomic-requirement-extraction-v1"
VERIFICATION_PROMPT_VERSION = "evidence-verification-v1"
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class OpenAIResearchError(RuntimeError):
    pass


class OpenAIConfigurationError(OpenAIResearchError):
    pass


class ExternalModelDataPolicyError(OpenAIResearchError):
    pass


class OpenAIProviderCallError(OpenAIResearchError):
    pass


class OpenAIStructuredOutputError(OpenAIResearchError):
    pass


class OpenAIRefusalError(OpenAIResearchError):
    pass


class OpenAIResearchConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, protected_namespaces=()
    )

    model_id: str = Field(default=DEFAULT_MODEL, min_length=1)
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "medium"
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)
    api_key_environment_variable: str = Field(default="OPENAI_API_KEY", min_length=1)
    allowed_data_classifications: tuple[DataClassification, ...] = (
        DataClassification.PUBLIC,
        DataClassification.SYNTHETIC,
    )

    @model_validator(mode="after")
    def reject_confidential_allow_list(self) -> OpenAIResearchConfig:
        prohibited = {DataClassification.CONFIDENTIAL, DataClassification.RESTRICTED}
        if prohibited & set(self.allowed_data_classifications):
            raise ValueError("research adapter cannot allow confidential or restricted data")
        return self


class _ResponsesResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _OpenAIClient(Protocol):
    responses: _ResponsesResource


def _canonical_json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    schema = model.model_json_schema()

    def harden(node: object) -> None:
        if isinstance(node, dict):
            node.pop("default", None)
            properties = node.get("properties")
            if isinstance(properties, dict):
                node["required"] = list(properties)
                node["additionalProperties"] = False
            for nested in node.values():
                harden(nested)
        elif isinstance(node, list):
            for nested in node:
                harden(nested)

    harden(schema)
    return schema


def _load_prompt(filename: str) -> str:
    return resources.files("ctrl_v2.evaluation.prompts").joinpath(filename).read_text(
        encoding="utf-8"
    )


def _attribute(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _token_usage(response: object) -> TokenUsage:
    usage = _attribute(response, "usage")
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=_attribute(usage, "input_tokens"),
        output_tokens=_attribute(usage, "output_tokens"),
        total_tokens=_attribute(usage, "total_tokens"),
    )


def _validate_response_shape(response: object) -> str:
    output = _attribute(response, "output", ()) or ()
    for item in output:
        item_type = str(_attribute(item, "type", ""))
        if "call" in item_type:
            raise OpenAIStructuredOutputError("unexpected tool or function call in response")
        for content in _attribute(item, "content", ()) or ():
            if _attribute(content, "type") == "refusal":
                raise OpenAIRefusalError("provider refused the structured request")
    output_text = _attribute(response, "output_text")
    if not isinstance(output_text, str) or not output_text.strip():
        raise OpenAIStructuredOutputError("provider returned no structured output text")
    return output_text


class OpenAIResponsesResearchAdapter(AtomicRequirementExtractor, EvidenceVerifier):
    """Research-only Responses API adapter; no production wiring or provider fallback."""

    def __init__(
        self,
        config: OpenAIResearchConfig | None = None,
        *,
        client: _OpenAIClient | None = None,
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.config = config or OpenAIResearchConfig()
        self._timer = timer
        if client is None:
            api_key = os.environ.get(self.config.api_key_environment_variable)
            if not api_key:
                raise OpenAIConfigurationError(
                    f"{self.config.api_key_environment_variable} is required "
                    "for real research calls"
                )
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise OpenAIConfigurationError(
                    "Install the pinned research extra to use the OpenAI adapter"
                ) from exc
            client = OpenAI(
                api_key=api_key,
                timeout=self.config.timeout_seconds,
                max_retries=self.config.max_retries,
            )
        self._client = client

    def _assert_external_data_allowed(self, classification: DataClassification) -> None:
        if classification not in self.config.allowed_data_classifications:
            raise ExternalModelDataPolicyError(
                f"External research calls are forbidden for {classification.value} data"
            )

    def _call_structured(
        self,
        *,
        prompt: str,
        prompt_version: str,
        payload: object,
        output_model: type[StructuredOutputT],
        schema_name: str,
        schema_version: str,
    ) -> tuple[StructuredOutputT, ModelCallRecord]:
        serialized_input = _canonical_json(payload)
        started = self._timer()
        try:
            response = self._client.responses.create(
                model=self.config.model_id,
                input=(
                    {"role": "developer", "content": prompt},
                    {"role": "user", "content": serialized_input},
                ),
                reasoning={"effort": self.config.reasoning_effort},
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": _strict_json_schema(output_model),
                        "strict": True,
                    }
                },
                store=False,
                tools=[],
                tool_choice="none",
                timeout=self.config.timeout_seconds,
            )
        except OpenAIResearchError:
            raise
        except Exception as exc:
            raise OpenAIProviderCallError("OpenAI Responses API research call failed") from exc
        latency_ms = max(self._timer() - started, 0.0) * 1000
        output_text = _validate_response_shape(response)
        try:
            parsed = output_model.model_validate_json(output_text)
        except Exception as exc:
            raise OpenAIStructuredOutputError(
                "provider output failed the versioned Pydantic contract"
            ) from exc
        serialized_output = _canonical_json(parsed)
        return parsed, ModelCallRecord(
            provider="openai",
            model_id=self.config.model_id,
            prompt_version=prompt_version,
            schema_version=schema_version,
            reasoning_effort=self.config.reasoning_effort,
            input_sha256=_sha256(serialized_input),
            output_sha256=_sha256(serialized_output),
            latency_ms=latency_ms,
            token_usage=_token_usage(response),
        )

    def extract(self, requirement: RawRequirement) -> AtomicExtractionResult:
        self._assert_external_data_allowed(requirement.data_classification)
        output, record = self._call_structured(
            prompt=_load_prompt("atomic_requirement_extraction_v1.txt"),
            prompt_version=EXTRACTION_PROMPT_VERSION,
            payload=requirement,
            output_model=AtomicExtractionOutput,
            schema_name="ctrl_atomic_requirement_extraction_v1",
            schema_version="1.0",
        )
        return AtomicExtractionResult(output=output, model_call=record)

    def verify(
        self,
        request: EvidenceVerificationRequest,
    ) -> tuple[EvidenceVerificationOutput, ModelCallRecord]:
        self._assert_external_data_allowed(request.data_classification)
        return self._call_structured(
            prompt=_load_prompt("evidence_verification_v1.txt"),
            prompt_version=VERIFICATION_PROMPT_VERSION,
            payload=request,
            output_model=EvidenceVerificationOutput,
            schema_name="ctrl_evidence_verification_v1",
            schema_version="1.0",
        )
