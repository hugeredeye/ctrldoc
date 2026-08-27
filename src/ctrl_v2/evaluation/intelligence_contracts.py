from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ctrl_v2.application.structured_contracts import SourceLocator
from ctrl_v2.domain.enums import EvidenceAuthorityLevel, EvidenceSourceType
from ctrl_v2.evaluation.retrieval_contracts import RetrievedEvidenceSpan


class IntelligenceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, protected_namespaces=()
    )


class DataClassification(StrEnum):
    PUBLIC = "PUBLIC"
    DEMO = "DEMO"
    SYNTHETIC = "SYNTHETIC"
    SYNTHETIC_SAFE = "SYNTHETIC_SAFE"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"
    PERSONAL_DATA = "PERSONAL_DATA"
    CUSTOMER_CONFIDENTIAL = "CUSTOMER_CONFIDENTIAL"


class RequirementModality(StrEnum):
    MUST = "MUST"
    SHOULD = "SHOULD"
    MAY = "MAY"
    PROHIBITED = "PROHIBITED"
    UNKNOWN = "UNKNOWN"


class QuantitativeComparator(StrEnum):
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN_OR_EQUAL = "<="
    EQUAL = "="
    GREATER_THAN = ">"
    LESS_THAN = "<"


class QuantitativeConstraint(IntelligenceModel):
    comparator: QuantitativeComparator
    value: str = Field(min_length=1, pattern=r"^[0-9][0-9 .,]*$")
    unit: str = Field(min_length=1)


class RawRequirement(IntelligenceModel):
    requirement_id: str = Field(min_length=1)
    original_text: str = Field(min_length=1)
    source_context: str | None = None
    source_locator: SourceLocator
    document_version_id: str | None = None
    data_classification: DataClassification


class AtomicRequirement(IntelligenceModel):
    atomic_id: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    original_source_text: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    source_start_offset: int = Field(ge=0)
    source_end_offset: int = Field(gt=0)
    source_locator: SourceLocator
    modality: RequirementModality
    category: str | None = None
    quantitative_constraint: QuantitativeConstraint | None = None
    negated: bool = False
    dependency_atomic_ids: tuple[str, ...] = ()
    conjunction_group: str | None = None
    ambiguous: bool = False
    clarification_needed: bool = False
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_offsets_and_clarification(self) -> AtomicRequirement:
        if self.source_end_offset <= self.source_start_offset:
            raise ValueError("source_end_offset must be greater than source_start_offset")
        if self.clarification_needed and not self.clarification_question:
            raise ValueError("clarification_needed requires a clarification_question")
        if not self.clarification_needed and self.clarification_question is not None:
            raise ValueError("clarification_question requires clarification_needed")
        return self


class AtomicExtractionOutput(IntelligenceModel):
    schema_version: Literal["1.0"] = "1.0"
    requirements: tuple[AtomicRequirement, ...]


class TokenUsage(IntelligenceModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ProviderCallConfiguration(IntelligenceModel):
    api_style: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    endpoint_url: str | None = None
    requested_model_id: str = Field(min_length=1)
    inference_mode: str | None = None
    thinking_enabled: bool | None = None
    reasoning_effort: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    timeout_seconds: float = Field(gt=0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    transport_max_retries: int = Field(default=0, ge=0)
    output_max_retries: int = Field(default=0, ge=0)
    json_mode: str = Field(min_length=1)
    tools_enabled: bool


class ModelCallRecord(IntelligenceModel):
    provider: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    finish_reason: str | None = None
    latency_ms: float = Field(ge=0)
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    retry_count: int = Field(default=0, ge=0)
    failure_reasons: tuple[str, ...] = ()
    provider_configuration: ProviderCallConfiguration | None = None
    estimated_cost: float | None = Field(default=None, ge=0)
    cost_currency: str | None = None


class AtomicExtractionResult(IntelligenceModel):
    output: AtomicExtractionOutput
    model_call: ModelCallRecord | None = None


class ValidationIssueCode(StrEnum):
    EMPTY_ATOMIC = "EMPTY_ATOMIC"
    DUPLICATE_ATOMIC = "DUPLICATE_ATOMIC"
    INVENTED_NUMERIC_CONSTRAINT = "INVENTED_NUMERIC_CONSTRAINT"
    UNIT_CHANGED = "UNIT_CHANGED"
    COMPARATOR_CHANGED = "COMPARATOR_CHANGED"
    POLARITY_REVERSED = "POLARITY_REVERSED"
    MODALITY_CHANGED = "MODALITY_CHANGED"
    SOURCE_LOCATOR_LOST = "SOURCE_LOCATOR_LOST"
    SOURCE_RELATION_UNRECOVERABLE = "SOURCE_RELATION_UNRECOVERABLE"
    AMBIGUOUS_SOURCE_ANCHOR = "AMBIGUOUS_SOURCE_ANCHOR"
    ORIGINAL_SOURCE_CHANGED = "ORIGINAL_SOURCE_CHANGED"
    NON_ATOMIC_CONJUNCTION = "NON_ATOMIC_CONJUNCTION"
    AMBIGUOUS_REQUIREMENT = "AMBIGUOUS_REQUIREMENT"
    UNKNOWN_PRODUCT_VERSION = "UNKNOWN_PRODUCT_VERSION"
    UNKNOWN_CAPABILITY = "UNKNOWN_CAPABILITY"
    UNKNOWN_PRODUCT = "UNKNOWN_PRODUCT"


class ValidationIssue(IntelligenceModel):
    code: ValidationIssueCode
    atomic_id: str | None = None
    message: str = Field(min_length=1)
    blocking: bool


class SourceAnchorResolution(IntelligenceModel):
    atomic_id: str = Field(min_length=1)
    provider_start_offset: int = Field(ge=0)
    provider_end_offset: int = Field(gt=0)
    canonical_start_offset: int | None = Field(default=None, ge=0)
    canonical_end_offset: int | None = Field(default=None, gt=0)
    exact_match_count: int = Field(ge=0)
    offsets_corrected: bool

    @model_validator(mode="after")
    def validate_canonical_offsets(self) -> SourceAnchorResolution:
        has_canonical_offsets = (
            self.canonical_start_offset is not None
            and self.canonical_end_offset is not None
        )
        if self.exact_match_count == 1 and not has_canonical_offsets:
            raise ValueError("a unique source anchor requires canonical offsets")
        if self.exact_match_count != 1 and has_canonical_offsets:
            raise ValueError("non-unique source anchors cannot have canonical offsets")
        if self.offsets_corrected and self.exact_match_count != 1:
            raise ValueError("only a unique source anchor can correct offsets")
        if has_canonical_offsets:
            assert self.canonical_start_offset is not None
            assert self.canonical_end_offset is not None
            if self.canonical_end_offset <= self.canonical_start_offset:
                raise ValueError("canonical end offset must be greater than start offset")
            expected_correction = (
                self.provider_start_offset != self.canonical_start_offset
                or self.provider_end_offset != self.canonical_end_offset
            )
            if self.offsets_corrected != expected_correction:
                raise ValueError("offset correction flag does not match canonical offsets")
        return self


class ExtractionValidationResult(IntelligenceModel):
    accepted: tuple[AtomicRequirement, ...]
    rejected: tuple[AtomicRequirement, ...]
    issues: tuple[ValidationIssue, ...]
    source_anchor_resolutions: tuple[SourceAnchorResolution, ...] = ()
    requires_human_review: bool


class ProductCandidate(IntelligenceModel):
    product_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()


class ProductVersionCandidate(IntelligenceModel):
    product_version_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    version_label: str = Field(min_length=1)
    valid_from: date
    valid_to: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> ProductVersionCandidate:
        if self.valid_to is not None and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not be after valid_to")
        return self


class CapabilityCandidate(IntelligenceModel):
    capability_id: str = Field(min_length=1)
    product_id: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()


class ControlledProductCatalog(IntelligenceModel):
    products: tuple[ProductCandidate, ...]
    product_versions: tuple[ProductVersionCandidate, ...]
    capabilities: tuple[CapabilityCandidate, ...]

    @model_validator(mode="after")
    def validate_references(self) -> ControlledProductCatalog:
        product_ids = {item.product_id for item in self.products}
        if len(product_ids) != len(self.products):
            raise ValueError("product IDs must be unique")
        version_ids = {item.product_version_id for item in self.product_versions}
        capability_ids = {item.capability_id for item in self.capabilities}
        if len(version_ids) != len(self.product_versions):
            raise ValueError("product version IDs must be unique")
        if len(capability_ids) != len(self.capabilities):
            raise ValueError("capability IDs must be unique")
        if any(item.product_id not in product_ids for item in self.product_versions):
            raise ValueError("product version references an unknown product")
        if any(item.product_id not in product_ids for item in self.capabilities):
            raise ValueError("capability references an unknown product")
        return self


class MappingDisposition(StrEnum):
    MATCH = "MATCH"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"


class RequirementMappingCandidate(IntelligenceModel):
    requirement_id: str = Field(min_length=1)
    disposition: MappingDisposition
    product_id: str | None = None
    product_version_id: str | None = None
    capability_id: str | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    matching_terms: tuple[str, ...] = ()
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_disposition(self) -> RequirementMappingCandidate:
        entity_ids = (self.product_id, self.product_version_id, self.capability_id)
        if self.disposition == MappingDisposition.NO_MATCH:
            if any(value is not None for value in entity_ids) or self.score is not None:
                raise ValueError("NO_MATCH cannot identify a controlled entity")
        elif any(value is None for value in entity_ids) or self.score is None:
            raise ValueError("matched mapping requires product, version, capability, and score")
        return self


class MappingResult(IntelligenceModel):
    candidates: tuple[RequirementMappingCandidate, ...]
    issues: tuple[ValidationIssue, ...] = ()
    selected: RequirementMappingCandidate | None = None
    requires_human_review: bool


class VerificationLabel(StrEnum):
    ENTAILS = "ENTAILS"
    CONTRADICTS = "CONTRADICTS"
    INSUFFICIENT = "INSUFFICIENT"


class VerificationReasonTag(StrEnum):
    WRONG_VERSION = "WRONG_VERSION"
    WRONG_METRIC = "WRONG_METRIC"
    INSUFFICIENT_LIMIT = "INSUFFICIENT_LIMIT"
    ROADMAP_ONLY = "ROADMAP_ONLY"
    OBSOLETE_SOURCE = "OBSOLETE_SOURCE"
    TEMPORALLY_INVALID = "TEMPORALLY_INVALID"
    LOWER_AUTHORITY = "LOWER_AUTHORITY"
    PARTIAL_SUPPORT = "PARTIAL_SUPPORT"
    SEMANTIC_NEIGHBOR_ONLY = "SEMANTIC_NEIGHBOR_ONLY"
    AMBIGUOUS_SOURCE = "AMBIGUOUS_SOURCE"
    INCOMPLETE_PROVENANCE = "INCOMPLETE_PROVENANCE"


class EvidenceVerificationOutput(IntelligenceModel):
    schema_version: Literal["1.0"] = "1.0"
    label: VerificationLabel
    reason_tags: tuple[VerificationReasonTag, ...] = ()
    explanation: str = Field(min_length=1, max_length=1000)
    unsupported_portion: str | None = None

    @model_validator(mode="after")
    def validate_partial_support(self) -> EvidenceVerificationOutput:
        if VerificationReasonTag.PARTIAL_SUPPORT in self.reason_tags:
            if not self.unsupported_portion:
                raise ValueError("PARTIAL_SUPPORT requires unsupported_portion")
        elif self.unsupported_portion is not None:
            raise ValueError("unsupported_portion requires PARTIAL_SUPPORT")
        return self


class EvidenceVerificationRequest(IntelligenceModel):
    requirement: AtomicRequirement
    mapping: RequirementMappingCandidate
    evidence: RetrievedEvidenceSpan
    product_version: ProductVersionCandidate
    assessment_as_of: date
    data_classification: DataClassification


class EvidenceVerificationResult(IntelligenceModel):
    evidence_span_id: str = Field(min_length=1)
    provider_output: EvidenceVerificationOutput
    effective_output: EvidenceVerificationOutput
    guardrail_adjustments: tuple[VerificationReasonTag, ...] = ()
    model_call: ModelCallRecord | None = None


class ConflictEvidenceContext(IntelligenceModel):
    evidence_span_id: str = Field(min_length=1)
    provider_label: VerificationLabel
    effective_label: VerificationLabel
    authority_level: EvidenceAuthorityLevel
    source_type: EvidenceSourceType
    document_version: str = Field(min_length=1)
    product_version_id: str | None = None
    valid_from: date
    valid_to: date | None = None


class EvidenceConflict(IntelligenceModel):
    present: bool
    material: bool
    evidence_span_ids: tuple[str, ...] = ()
    contexts: tuple[ConflictEvidenceContext, ...] = ()
    explanation: str | None = None
    requires_human_review: bool


class GuardedComplianceStatus(StrEnum):
    COMPLY = "COMPLY"
    PARTIAL = "PARTIAL"
    GAP = "GAP"
    UNKNOWN = "UNKNOWN"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class GuardedComplianceDecision(IntelligenceModel):
    status: GuardedComplianceStatus
    product_version_id: str | None = None
    capability_id: str | None = None
    supporting_evidence_span_ids: tuple[str, ...] = ()
    contradicting_evidence_span_ids: tuple[str, ...] = ()
    unsupported_portions: tuple[str, ...] = ()
    uncertainty_reasons: tuple[str, ...] = ()
    policy_version: Literal["guarded-compliance-v1"] = "guarded-compliance-v1"
    requires_human_review: Literal[True] = True
    auto_approved: Literal[False] = False


class RetrievalMetadata(IntelligenceModel):
    retriever_implementation_id: str = Field(min_length=1)
    retriever_method: str = Field(min_length=1)
    embedding_model_id: str | None = None
    reranker_implementation_id: str = Field(min_length=1)
    reranker_model_id: str | None = None
    candidate_limit: int = Field(gt=0)
    final_limit: int = Field(gt=0)


class AtomicIntelligenceResult(IntelligenceModel):
    original_requirement: RawRequirement
    atomic_requirement: AtomicRequirement
    mapping: MappingResult
    candidate_evidence: tuple[RetrievedEvidenceSpan, ...]
    verifications: tuple[EvidenceVerificationResult, ...]
    conflict: EvidenceConflict
    proposed_decision: GuardedComplianceDecision
    retrieval_metadata: RetrievalMetadata | None = None
    model_calls: tuple[ModelCallRecord, ...] = ()
    requires_human_review: Literal[True] = True


class ProductIntelligenceResult(IntelligenceModel):
    schema_version: Literal["1.0"] = "1.0"
    original_requirement: RawRequirement
    extraction: ExtractionValidationResult
    atomic_results: tuple[AtomicIntelligenceResult, ...]
    model_calls: tuple[ModelCallRecord, ...]
    requires_human_review: Literal[True] = True
    auto_approved: Literal[False] = False


@runtime_checkable
class AtomicRequirementExtractor(Protocol):
    def extract(self, requirement: RawRequirement) -> AtomicExtractionResult: ...


@runtime_checkable
class CapabilityMapper(Protocol):
    def map_requirement(
        self,
        requirement: AtomicRequirement,
        catalog: ControlledProductCatalog,
        *,
        assessment_as_of: date,
    ) -> tuple[RequirementMappingCandidate, ...]: ...


@runtime_checkable
class EvidenceVerifier(Protocol):
    def verify(self, request: EvidenceVerificationRequest) -> tuple[
        EvidenceVerificationOutput,
        ModelCallRecord | None,
    ]: ...
