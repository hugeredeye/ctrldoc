from __future__ import annotations

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

    @model_validator(mode="after")
    def validate_offsets(self) -> GoldAtomicRequirement:
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
    gold_atomic_requirements: tuple[GoldAtomicRequirement, ...] = Field(min_length=1)
    gold_mappings: tuple[GoldMapping, ...]
    gold_evidence_spans: tuple[GoldEvidenceSpan, ...]
    hard_negative_evidence: tuple[GoldHardNegativeEvidence, ...] = ()
    gold_compliance_outcomes: tuple[GoldComplianceOutcome, ...] = Field(min_length=1)

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
        outcome_keys = {item.atomic_requirement_key for item in self.gold_compliance_outcomes}
        missing_outcomes = atomic_keys - outcome_keys
        if missing_outcomes:
            raise ValueError(
                f"gold compliance outcome is missing for atomic keys: {sorted(missing_outcomes)}"
            )
        positive_keys = {item.key for item in self.gold_evidence_spans if item.key is not None}
        hard_negative_keys = {
            item.key for item in self.hard_negative_evidence if item.key is not None
        }
        overlap = positive_keys & hard_negative_keys
        if overlap:
            raise ValueError(
                f"evidence cannot be both positive and hard-negative: {sorted(overlap)}"
            )
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
        return self


def assert_checked_in_fixture(dataset: GoldDataset) -> None:
    if dataset.scope != DatasetScope.CHECKED_IN_TEST:
        raise ValueError("checked-in fixture must declare CHECKED_IN_TEST scope")
    if dataset.contains_customer_data:
        raise ValueError("checked-in fixture cannot contain customer data")
    serialized = dataset.model_dump(mode="json")

    def visit(value: object) -> None:
        if isinstance(value, dict):
            prohibited = _PROHIBITED_PROVENANCE_KEYS & {str(key).casefold() for key in value}
            if prohibited:
                raise ValueError(
                    f"checked-in fixture contains tenant identifiers: {sorted(prohibited)}"
                )
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(serialized)
