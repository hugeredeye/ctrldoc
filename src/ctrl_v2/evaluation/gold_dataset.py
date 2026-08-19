from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ctrl_v2.application.structured_contracts import SourceLocator
from ctrl_v2.domain.enums import EvidenceAuthorityLevel, EvidenceSourceType

_PROHIBITED_PROVENANCE_KEYS = {
    "customer_id",
    "organization_id",
    "tenant_id",
    "workspace_id",
}


class GoldComplianceLabel(StrEnum):
    COMPLY = "COMPLY"
    PARTIAL = "PARTIAL"
    GAP = "GAP"
    UNKNOWN = "UNKNOWN"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class DatasetScope(StrEnum):
    CHECKED_IN_TEST = "CHECKED_IN_TEST"
    EXTERNAL_RESTRICTED = "EXTERNAL_RESTRICTED"


class HardNegativeErrorTag(StrEnum):
    WRONG_PRODUCT_VERSION = "WRONG_PRODUCT_VERSION"
    OBSOLETE_SOURCE = "OBSOLETE_SOURCE"
    ROADMAP_NOT_RELEASED = "ROADMAP_NOT_RELEASED"
    NON_ENTAILING = "NON_ENTAILING"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    TEMPORAL_VALIDITY = "TEMPORAL_VALIDITY"
    SOURCE_AUTHORITY = "SOURCE_AUTHORITY"
    RELATED_FEATURE_MISSING_CAPABILITY = "RELATED_FEATURE_MISSING_CAPABILITY"
    SAME_TERMINOLOGY_DIFFERENT_SEMANTICS = "SAME_TERMINOLOGY_DIFFERENT_SEMANTICS"
    INSUFFICIENT_QUANTITATIVE_LIMIT = "INSUFFICIENT_QUANTITATIVE_LIMIT"
    LOWER_AUTHORITY_CONTRADICTION = "LOWER_AUTHORITY_CONTRADICTION"
    PARTIAL_COMPOUND_EVIDENCE = "PARTIAL_COMPOUND_EVIDENCE"
    PREVIOUS_RESPONSE_UNVERIFIED = "PREVIOUS_RESPONSE_UNVERIFIED"


class RequirementLanguage(StrEnum):
    RU = "RU"
    EN = "EN"
    MIXED = "MIXED"
    OTHER = "OTHER"


class BenchmarkSourceCategory(StrEnum):
    PRODUCT_DOCUMENTATION = "PRODUCT_DOCUMENTATION"
    CERTIFICATION_OR_TEST = "CERTIFICATION_OR_TEST"
    RELEASE_OR_ROADMAP = "RELEASE_OR_ROADMAP"
    RFP_OR_TENDER = "RFP_OR_TENDER"
    PREVIOUS_APPROVED_RESPONSE = "PREVIOUS_APPROVED_RESPONSE"
    INTERNAL_KNOWLEDGE = "INTERNAL_KNOWLEDGE"
    OTHER = "OTHER"


class AnnotationReviewStatus(StrEnum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    ADJUDICATED = "ADJUDICATED"
    FROZEN = "FROZEN"


class GoldModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _validate_asset_path(asset_path: str) -> None:
    normalized = asset_path.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized or ".." in normalized.split("/"):
        raise ValueError("asset_path must be dataset-relative and cannot traverse directories")


class GoldSourceRequirement(GoldModel):
    asset_path: str = Field(min_length=1, description="Dataset-relative source document path")
    source_text: str = Field(min_length=1)
    context: str | None = None
    locator: SourceLocator

    @model_validator(mode="after")
    def validate_asset_path(self) -> GoldSourceRequirement:
        _validate_asset_path(self.asset_path)
        return self


class GoldAtomicRequirement(GoldModel):
    key: str = Field(min_length=1)
    atomic_text: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)
    source_start_offset: int = Field(ge=0)
    source_end_offset: int = Field(gt=0)
    modality: str = Field(min_length=1)
    language: RequirementLanguage | None = None

    @model_validator(mode="after")
    def validate_offsets(self) -> GoldAtomicRequirement:
        if not self.atomic_text.strip():
            raise ValueError("atomic_text cannot be blank")
        if self.source_end_offset <= self.source_start_offset:
            raise ValueError("source_end_offset must be greater than source_start_offset")
        return self


class GoldMapping(GoldModel):
    atomic_requirement_key: str
    product_key: str | None = None
    product_version_key: str | None = None
    capability_key: str | None = None


class GoldEvidenceSpan(GoldModel):
    key: str | None = None
    atomic_requirement_key: str
    product_version_key: str | None = None
    asset_path: str = Field(min_length=1)
    document_key: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_type: EvidenceSourceType
    authority_level: EvidenceAuthorityLevel
    valid_from: date
    valid_to: date | None = None
    exact_quote: str = Field(min_length=1)
    locator: SourceLocator

    @model_validator(mode="after")
    def validate_provenance(self) -> GoldEvidenceSpan:
        if self.valid_to is not None and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not be after valid_to")
        _validate_asset_path(self.asset_path)
        return self


class GoldHardNegativeEvidence(GoldEvidenceSpan):
    reason: str = Field(min_length=1)
    error_tags: tuple[HardNegativeErrorTag, ...] = ()


class GoldIndependentReview(GoldModel):
    status: AnnotationReviewStatus = AnnotationReviewStatus.DRAFT
    reviewer_alias: str | None = None
    reviewed_at: datetime | None = None
    disagreement: str | None = None
    adjudicator_alias: str | None = None
    adjudicated_at: datetime | None = None
    adjudication_note: str | None = None
    frozen_at: datetime | None = None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> GoldIndependentReview:
        text_fields = {
            "reviewer_alias": self.reviewer_alias,
            "disagreement": self.disagreement,
            "adjudicator_alias": self.adjudicator_alias,
            "adjudication_note": self.adjudication_note,
        }
        blank = sorted(
            name for name, value in text_fields.items() if value is not None and not value.strip()
        )
        if blank:
            raise ValueError(f"review text fields cannot be blank: {blank}")
        review_fields = (self.reviewer_alias, self.reviewed_at)
        adjudication_fields = (
            self.adjudicator_alias,
            self.adjudicated_at,
            self.adjudication_note,
        )
        if self.status == AnnotationReviewStatus.DRAFT:
            if any(value is not None for value in (*review_fields, *adjudication_fields)):
                raise ValueError("DRAFT review cannot contain review or adjudication records")
            if self.frozen_at is not None or self.disagreement is not None:
                raise ValueError("DRAFT review cannot contain disagreement or freeze records")
            return self
        if any(value is None for value in review_fields):
            raise ValueError(f"{self.status.value} requires reviewer_alias and reviewed_at")
        if self.status == AnnotationReviewStatus.REVIEWED:
            has_adjudication = any(value is not None for value in adjudication_fields)
            if has_adjudication or self.frozen_at is not None:
                raise ValueError("REVIEWED cannot contain adjudication or freeze records")
            return self
        if self.status == AnnotationReviewStatus.ADJUDICATED:
            if not self.disagreement or not self.disagreement.strip():
                raise ValueError("ADJUDICATED requires a recorded disagreement")
            if any(value is None for value in adjudication_fields):
                raise ValueError("ADJUDICATED requires adjudicator, time, and note")
            if self.frozen_at is not None:
                raise ValueError("ADJUDICATED cannot contain frozen_at")
            return self
        if self.frozen_at is None:
            raise ValueError("FROZEN requires frozen_at")
        if self.disagreement and any(value is None for value in adjudication_fields):
            raise ValueError("FROZEN disagreement requires complete adjudication")
        if not self.disagreement and any(value is not None for value in adjudication_fields):
            raise ValueError("FROZEN adjudication requires a recorded disagreement")
        return self


class GoldBenchmarkGrouping(GoldModel):
    document_family: str = Field(min_length=1)
    source_case_family: str = Field(min_length=1)
    product_family: str | None = None
    product_version_family: str | None = None


class GoldBenchmarkCaseMetadata(GoldModel):
    source_category: BenchmarkSourceCategory
    grouping: GoldBenchmarkGrouping
    review: GoldIndependentReview = Field(default_factory=GoldIndependentReview)


class GoldAnnotation(GoldModel):
    annotator: str = Field(min_length=1)
    annotation_version: str = Field(min_length=1)
    annotated_at: datetime


class GoldProvenance(GoldModel):
    source_collection: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    notes: str | None = None


class GoldComplianceOutcome(GoldModel):
    atomic_requirement_key: str
    product_version_key: str | None = None
    assessment_as_of: date
    outcome: GoldComplianceLabel
    critical: bool = False


class GoldCase(GoldModel):
    case_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    description: str = Field(min_length=1)
    source_requirement: GoldSourceRequirement
    annotation: GoldAnnotation
    provenance: GoldProvenance
    benchmark: GoldBenchmarkCaseMetadata | None = None
    gold_atomic_requirements: tuple[GoldAtomicRequirement, ...] = Field(min_length=1)
    gold_mappings: tuple[GoldMapping, ...]
    gold_evidence_spans: tuple[GoldEvidenceSpan, ...]
    hard_negative_evidence: tuple[GoldHardNegativeEvidence, ...] = ()
    gold_compliance_outcomes: tuple[GoldComplianceOutcome, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> GoldCase:
        atomic_keys = {item.key for item in self.gold_atomic_requirements}
        if len(atomic_keys) != len(self.gold_atomic_requirements):
            raise ValueError("gold atomic requirement keys must be unique")
        for atomic in self.gold_atomic_requirements:
            if atomic.source_end_offset > len(self.source_requirement.source_text):
                raise ValueError(f"source offsets are out of range for {atomic.key}")
            actual_quote = self.source_requirement.source_text[
                atomic.source_start_offset : atomic.source_end_offset
            ]
            if actual_quote != atomic.source_quote:
                raise ValueError(f"source quote does not match exact offsets for {atomic.key}")
        referenced_atomic_keys = {
            item.atomic_requirement_key
            for item in (
                *self.gold_mappings,
                *self.gold_evidence_spans,
                *self.hard_negative_evidence,
                *self.gold_compliance_outcomes,
            )
        }
        unknown = referenced_atomic_keys - atomic_keys
        if unknown:
            raise ValueError(f"gold records reference unknown atomic keys: {sorted(unknown)}")
        outcome_keys = [item.atomic_requirement_key for item in self.gold_compliance_outcomes]
        if len(outcome_keys) != len(set(outcome_keys)):
            raise ValueError("gold compliance outcomes must be unique per atomic requirement")
        positive_keys = {item.key for item in self.gold_evidence_spans if item.key is not None}
        hard_negative_keys = {
            item.key for item in self.hard_negative_evidence if item.key is not None
        }
        overlap = positive_keys & hard_negative_keys
        if overlap:
            raise ValueError(
                f"evidence cannot be both positive and hard-negative: {sorted(overlap)}"
            )
        positive_content = {
            evidence_span_content_identity(item) for item in self.gold_evidence_spans
        }
        hard_negative_content = {
            evidence_span_content_identity(item) for item in self.hard_negative_evidence
        }
        content_overlap = positive_content & hard_negative_content
        if content_overlap:
            raise ValueError("the same evidence content cannot be positive and hard-negative")
        return self


class GoldDataset(GoldModel):
    schema_version: Literal["2.0"] = "2.0"
    dataset_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    created_at: datetime
    scope: DatasetScope
    contains_customer_data: bool
    cases: tuple[GoldCase, ...] = ()

    @model_validator(mode="after")
    def validate_dataset(self) -> GoldDataset:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("gold case IDs must be unique")
        if self.scope == DatasetScope.CHECKED_IN_TEST and self.contains_customer_data:
            raise ValueError("checked-in evaluation fixtures cannot contain customer data")
        evidence_keys: list[str] = []
        evidence_content: list[str] = []
        for case in self.cases:
            for span in (*case.gold_evidence_spans, *case.hard_negative_evidence):
                if span.key is not None:
                    evidence_keys.append(span.key)
                evidence_content.append(evidence_span_content_identity(span))
        if len(evidence_keys) != len(set(evidence_keys)):
            raise ValueError("EvidenceSpan keys must be unique across the dataset")
        if len(evidence_content) != len(set(evidence_content)):
            raise ValueError("EvidenceSpan provenance/content identities must be unique")
        return self


def evidence_span_content_identity(span: GoldEvidenceSpan) -> str:
    payload = json.dumps(
        {
            "asset_path": span.asset_path,
            "document_key": span.document_key,
            "document_version": span.document_version,
            "exact_quote": span.exact_quote,
            "locator": span.locator.model_dump(mode="json"),
            "product_version_key": span.product_version_key,
            "source_sha256": span.source_sha256,
            "valid_from": span.valid_from.isoformat(),
            "valid_to": span.valid_to.isoformat() if span.valid_to else None,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assert_no_prohibited_identifier_fields(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).casefold()
            nested_path = f"{path}.{key}"
            if normalized in _PROHIBITED_PROVENANCE_KEYS:
                raise ValueError(f"forbidden benchmark identifier field at {nested_path}")
            assert_no_prohibited_identifier_fields(nested, nested_path)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            assert_no_prohibited_identifier_fields(nested, f"{path}[{index}]")


def assert_checked_in_fixture(dataset: GoldDataset) -> None:
    if dataset.scope != DatasetScope.CHECKED_IN_TEST:
        raise ValueError("checked-in fixture must declare CHECKED_IN_TEST scope")
    if dataset.contains_customer_data:
        raise ValueError("checked-in fixture cannot contain customer data")
    assert_no_prohibited_identifier_fields(dataset.model_dump(mode="json"))
