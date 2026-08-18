from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ctrl_v2.application.structured_contracts import SourceLocator
from ctrl_v2.domain.enums import (
    ComplianceOutcome,
    EvidenceAuthorityLevel,
    EvidenceSourceType,
)


class GoldModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GoldSourceRequirement(GoldModel):
    asset_path: str = Field(min_length=1, description="Dataset-relative source document path")
    source_text: str = Field(min_length=1)
    locator: SourceLocator

    @model_validator(mode="after")
    def validate_asset_path(self) -> GoldSourceRequirement:
        normalized = self.asset_path.replace("\\", "/")
        if normalized.startswith("/") or ":" in normalized or ".." in normalized.split("/"):
            raise ValueError("asset_path must be dataset-relative and cannot traverse directories")
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
    product_key: str
    product_version_key: str
    capability_key: str


class GoldEvidenceSpan(GoldModel):
    key: str
    atomic_requirement_key: str
    product_version_key: str
    asset_path: str = Field(min_length=1)
    source_type: EvidenceSourceType
    authority_level: EvidenceAuthorityLevel
    valid_from: date
    valid_to: date | None = None
    exact_quote: str = Field(min_length=1)
    locator: SourceLocator

    @model_validator(mode="after")
    def validate_temporal_scope(self) -> GoldEvidenceSpan:
        if self.valid_to is not None and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not be after valid_to")
        return self


class GoldComplianceOutcome(GoldModel):
    atomic_requirement_key: str
    product_version_key: str
    assessment_as_of: date
    outcome: ComplianceOutcome
    critical: bool = False


class GoldCase(GoldModel):
    case_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    description: str = Field(min_length=1)
    source_requirement: GoldSourceRequirement
    gold_atomic_requirements: tuple[GoldAtomicRequirement, ...] = Field(min_length=1)
    gold_mappings: tuple[GoldMapping, ...]
    gold_evidence_spans: tuple[GoldEvidenceSpan, ...]
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
        return self


class GoldDataset(GoldModel):
    schema_version: Literal["1.0"] = "1.0"
    dataset_id: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9._-]+$")
    version: str = Field(min_length=1)
    description: str = Field(min_length=1)
    created_at: datetime
    cases: tuple[GoldCase, ...] = ()

    @model_validator(mode="after")
    def validate_case_ids(self) -> GoldDataset:
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("gold case IDs must be unique")
        return self
