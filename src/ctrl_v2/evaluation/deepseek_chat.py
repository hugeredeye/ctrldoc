from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from importlib import resources
from typing import Any, Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicExtractionOutput,
    AtomicExtractionResult,
    AtomicRequirementExtractor,
    DataClassification,
    EvidenceVerificationOutput,
    EvidenceVerificationRequest,
    EvidenceVerifier,
    ModelCallRecord,
    ProviderCallConfiguration,
    RawRequirement,
    TokenUsage,
)

OFFICIAL_BASE_URL = "https://api.deepseek.com"
OFFICIAL_CHAT_COMPLETIONS_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-pro"
EXTRACTION_PROMPT_VERSION = "atomic-requirement-extraction-deepseek-v1"
VERIFICATION_PROMPT_VERSION = "evidence-verification-deepseek-v1"
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)

_SAFE_CLASSIFICATIONS = {
    DataClassification.PUBLIC,
    DataClassification.DEMO,
    DataClassification.SYNTHETIC,
    DataClassification.SYNTHETIC_SAFE,
}
_PROHIBITED_CLASSIFICATIONS = {
    DataClassification.CONFIDENTIAL,
    DataClassification.RESTRICTED,
    DataClassification.PERSONAL_DATA,
    DataClassification.CUSTOMER_CONFIDENTIAL,
}


class DeepSeekResearchError(RuntimeError):
    def __init__(
        self,
        failure_reason: str,
        *,
        retry_count: int = 0,
        failure_reasons: tuple[str, ...] = (),
        latency_ms: float = 0.0,
    ) -> None:
        super().__init__(f"DeepSeek research call failed safely: {failure_reason}")
        self.failure_reason = failure_reason
        self.retry_count = retry_count
        self.failure_reasons = failure_reasons or (failure_reason,)
        self.latency_ms = latency_ms


class DeepSeekConfigurationError(DeepSeekResearchError):
    pass


class DeepSeekDataPolicyError(DeepSeekResearchError):
    pass


class DeepSeekProviderCallError(DeepSeekResearchError):
    pass


class DeepSeekEmptyOutputError(DeepSeekResearchError):
    pass


class DeepSeekInvalidJSONError(DeepSeekResearchError):
    pass


class DeepSeekSchemaViolationError(DeepSeekResearchError):
    pass


class DeepSeekUnexpectedToolCallError(DeepSeekResearchError):
    pass


class DeepSeekTruncatedOutputError(DeepSeekResearchError):
    pass


class DeepSeekResearchConfig(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, protected_namespaces=()
    )

    model_id: Literal["deepseek-v4-pro"] = DEFAULT_MODEL
    thinking_enabled: bool = True
    reasoning_effort: Literal["low", "high", "max"] = "high"
    timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    max_output_tokens: int = Field(default=4096, gt=0)
    max_retries: int = Field(default=1, ge=0, le=3)
    api_key_environment_variable: Literal["DEEPSEEK_API_KEY"] = "DEEPSEEK_API_KEY"
    allowed_data_classifications: tuple[DataClassification, ...] = (
        DataClassification.PUBLIC,
        DataClassification.DEMO,
        DataClassification.SYNTHETIC,
        DataClassification.SYNTHETIC_SAFE,
    )

    @model_validator(mode="after")
    def validate_classification_boundary(self) -> DeepSeekResearchConfig:
        allowed = set(self.allowed_data_classifications)
        if allowed - _SAFE_CLASSIFICATIONS or allowed & _PROHIBITED_CLASSIFICATIONS:
            raise ValueError("DeepSeek research adapter can allow only public/demo/synthetic data")
        return self


class _ChatCompletionsResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class _ChatResource(Protocol):
    completions: _ChatCompletionsResource


class _DeepSeekClient(Protocol):
    chat: _ChatResource


class _RetryableOutputError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _default_client_factory(**kwargs: Any) -> _DeepSeekClient:
    try:
        from openai import OpenAI
    except ImportError:
        raise DeepSeekConfigurationError("OPENAI_COMPATIBLE_SDK_NOT_INSTALLED") from None
    return OpenAI(**kwargs)


def _attribute(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _canonical_json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _load_prompt(filename: str, output_model: type[BaseModel]) -> str:
    semantic_prompt = (
        resources.files("ctrl_v2.evaluation.prompts")
        .joinpath(filename)
        .read_text(encoding="utf-8")
    )
    schema = json.dumps(
        output_model.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{semantic_prompt}\n\nExpected JSON Schema:\n{schema}"


def _usage(response: object) -> TokenUsage:
    usage = _attribute(response, "usage")
    if usage is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=_attribute(usage, "prompt_tokens"),
        output_tokens=_attribute(usage, "completion_tokens"),
        total_tokens=_attribute(usage, "total_tokens"),
    )


def _sum_usage(usages: list[TokenUsage]) -> TokenUsage:
    def total(field: str) -> int | None:
        values = [getattr(usage, field) for usage in usages]
        present = [value for value in values if value is not None]
        return sum(present) if present else None

    return TokenUsage(
        input_tokens=total("input_tokens"),
        output_tokens=total("output_tokens"),
        total_tokens=total("total_tokens"),
    )


def _response_content(response: object) -> str:
    choices = _attribute(response, "choices", ()) or ()
    if not choices:
        raise _RetryableOutputError("EMPTY_OUTPUT")
    choice = choices[0]
    message = _attribute(choice, "message")
    tool_calls = _attribute(message, "tool_calls", ()) or ()
    if tool_calls:
        raise DeepSeekUnexpectedToolCallError("UNEXPECTED_TOOL_CALL")
    if _attribute(choice, "finish_reason") == "length":
        raise DeepSeekTruncatedOutputError("TRUNCATED_OUTPUT")
    content = _attribute(message, "content")
    if not isinstance(content, str) or not content.strip():
        raise _RetryableOutputError("EMPTY_OUTPUT")
    try:
        json.loads(content)
    except json.JSONDecodeError:
        raise _RetryableOutputError("INVALID_JSON") from None
    return content


class DeepSeekChatResearchAdapter(AtomicRequirementExtractor, EvidenceVerifier):
    """Official DeepSeek cloud adapter for public/synthetic research inputs only."""

    def __init__(
        self,
        config: DeepSeekResearchConfig | None = None,
        *,
        client: _DeepSeekClient | None = None,
        client_factory: Callable[..., _DeepSeekClient] | None = None,
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.config = config or DeepSeekResearchConfig()
        self._timer = timer
        if client is not None and client_factory is not None:
            raise DeepSeekConfigurationError("CLIENT_AND_FACTORY_ARE_MUTUALLY_EXCLUSIVE")
        if client is None:
            api_key = os.environ.get(self.config.api_key_environment_variable)
            if not api_key:
                raise DeepSeekConfigurationError("DEEPSEEK_API_KEY_MISSING")
            factory = client_factory or _default_client_factory
            try:
                client = factory(
                    api_key=api_key,
                    base_url=OFFICIAL_BASE_URL,
                    timeout=self.config.timeout_seconds,
                    max_retries=0,
                )
            except DeepSeekResearchError:
                raise
            except Exception:
                raise DeepSeekConfigurationError("CLIENT_INITIALIZATION_FAILED") from None
        self._client = client

    def _assert_external_data_allowed(self, classification: DataClassification) -> None:
        if (
            classification not in self.config.allowed_data_classifications
            or classification in _PROHIBITED_CLASSIFICATIONS
        ):
            raise DeepSeekDataPolicyError(f"DATA_CLASSIFICATION_BLOCKED:{classification.value}")

    def _provider_configuration(self) -> ProviderCallConfiguration:
        return ProviderCallConfiguration(
            api_style="openai-compatible-chat-completions",
            base_url=OFFICIAL_BASE_URL,
            endpoint_url=OFFICIAL_CHAT_COMPLETIONS_ENDPOINT,
            requested_model_id=self.config.model_id,
            thinking_enabled=self.config.thinking_enabled,
            reasoning_effort=(
                self.config.reasoning_effort if self.config.thinking_enabled else "disabled"
            ),
            timeout_seconds=self.config.timeout_seconds,
            max_output_tokens=self.config.max_output_tokens,
            transport_max_retries=0,
            output_max_retries=self.config.max_retries,
            json_mode="json_object+pydantic-strict-validation",
            tools_enabled=False,
        )

    def _call_structured(
        self,
        *,
        prompt: str,
        prompt_version: str,
        payload: object,
        output_model: type[StructuredOutputT],
        schema_version: str,
    ) -> tuple[StructuredOutputT, ModelCallRecord]:
        serialized_input = _canonical_json(payload)
        failure_reasons: list[str] = []
        usages: list[TokenUsage] = []
        started = self._timer()
        for attempt in range(self.config.max_retries + 1):
            request: dict[str, object] = {
                "model": self.config.model_id,
                "messages": (
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": serialized_input},
                ),
                "response_format": {"type": "json_object"},
                "max_tokens": self.config.max_output_tokens,
                "stream": False,
                "tools": [],
                "extra_body": {
                    "thinking": {
                        "type": "enabled" if self.config.thinking_enabled else "disabled"
                    }
                },
                "timeout": self.config.timeout_seconds,
            }
            if self.config.thinking_enabled:
                request["reasoning_effort"] = self.config.reasoning_effort
            try:
                response = self._client.chat.completions.create(**request)
            except Exception:
                latency_ms = max(self._timer() - started, 0.0) * 1000
                reasons = (*failure_reasons, "API_FAILURE")
                raise DeepSeekProviderCallError(
                    "API_FAILURE",
                    retry_count=attempt,
                    failure_reasons=reasons,
                    latency_ms=latency_ms,
                ) from None
            usages.append(_usage(response))
            try:
                content = _response_content(response)
            except _RetryableOutputError as exc:
                failure_reasons.append(exc.reason)
                if attempt < self.config.max_retries:
                    continue
                latency_ms = max(self._timer() - started, 0.0) * 1000
                error_type = (
                    DeepSeekEmptyOutputError
                    if exc.reason == "EMPTY_OUTPUT"
                    else DeepSeekInvalidJSONError
                )
                raise error_type(
                    exc.reason,
                    retry_count=attempt,
                    failure_reasons=tuple(failure_reasons),
                    latency_ms=latency_ms,
                ) from None
            except DeepSeekResearchError as exc:
                latency_ms = max(self._timer() - started, 0.0) * 1000
                raise type(exc)(
                    exc.failure_reason,
                    retry_count=attempt,
                    failure_reasons=(*failure_reasons, exc.failure_reason),
                    latency_ms=latency_ms,
                ) from None
            try:
                parsed = output_model.model_validate_json(content)
            except ValidationError:
                latency_ms = max(self._timer() - started, 0.0) * 1000
                raise DeepSeekSchemaViolationError(
                    "SCHEMA_INVALID",
                    retry_count=attempt,
                    failure_reasons=(*failure_reasons, "SCHEMA_INVALID"),
                    latency_ms=latency_ms,
                ) from None
            latency_ms = max(self._timer() - started, 0.0) * 1000
            serialized_output = _canonical_json(parsed)
            response_model = _attribute(response, "model")
            actual_model = (
                response_model
                if isinstance(response_model, str) and response_model
                else self.config.model_id
            )
            return parsed, ModelCallRecord(
                provider="deepseek",
                model_id=actual_model,
                prompt_version=prompt_version,
                schema_version=schema_version,
                reasoning_effort=(
                    self.config.reasoning_effort
                    if self.config.thinking_enabled
                    else "disabled"
                ),
                input_sha256=_sha256(serialized_input),
                output_sha256=_sha256(serialized_output),
                latency_ms=latency_ms,
                token_usage=_sum_usage(usages),
                retry_count=attempt,
                failure_reasons=tuple(failure_reasons),
                provider_configuration=self._provider_configuration(),
            )
        raise AssertionError("bounded DeepSeek attempt loop did not return or raise")

    def extract(self, requirement: RawRequirement) -> AtomicExtractionResult:
        self._assert_external_data_allowed(requirement.data_classification)
        output, record = self._call_structured(
            prompt=_load_prompt(
                "atomic_requirement_extraction_deepseek_v1.txt", AtomicExtractionOutput
            ),
            prompt_version=EXTRACTION_PROMPT_VERSION,
            payload=requirement,
            output_model=AtomicExtractionOutput,
            schema_version="1.0",
        )
        return AtomicExtractionResult(output=output, model_call=record)

    def verify(
        self,
        request: EvidenceVerificationRequest,
    ) -> tuple[EvidenceVerificationOutput, ModelCallRecord]:
        self._assert_external_data_allowed(request.data_classification)
        return self._call_structured(
            prompt=_load_prompt(
                "evidence_verification_deepseek_v1.txt", EvidenceVerificationOutput
            ),
            prompt_version=VERIFICATION_PROMPT_VERSION,
            payload=request,
            output_model=EvidenceVerificationOutput,
            schema_version="1.0",
        )
