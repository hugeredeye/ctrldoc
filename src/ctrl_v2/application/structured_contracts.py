from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from ctrl_v2.domain.enums import (
    ComplianceOutcome,
    EvidenceAuthorityLevel,
    EvidenceSourceType,
    ReviewRisk,
)


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PdfLocator(StrictContract):
    kind: Literal["PDF"] = "PDF"
    page: int = Field(ge=1)
    bbox: tuple[float, float, float, float] | None = None


class DocxLocator(StrictContract):
    kind: Literal["DOCX"] = "DOCX"
    section_path: tuple[str, ...] = ()
    paragraph_index: int | None = Field(default=None, ge=0)
    table_index: int | None = Field(default=None, ge=0)
    row_index: int | None = Field(default=None, ge=0)
    column_index: int | None = Field(default=None, ge=0)


class XlsxLocator(StrictContract):
    kind: Literal["XLSX"] = "XLSX"
    sheet: str
    cell_range: str
    table_name: str | None = None


SourceLocator = Annotated[PdfLocator | DocxLocator | XlsxLocator, Field(discriminator="kind")]


class SourceReference(StrictContract):
    document_version_id: str
    block_id: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    exact_quote: str = Field(min_length=1)
    locator: SourceLocator


class AtomicRequirementProposal(StrictContract):
    client_key: str
    atomic_text: str = Field(min_length=1)
    modality: str
    category: str | None = None
    acceptance_criteria: tuple[str, ...] = ()
    ambiguity_flags: tuple[str, ...] = ()
    sources: tuple[SourceReference, ...] = Field(min_length=1)


class AtomicRequirementExtractionBatch(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    input_snapshot_hash: str
    instruction_version: str
    requirements: tuple[AtomicRequirementProposal, ...]


class RequirementMappingProposal(StrictContract):
    requirement_id: str
    product_version_id: str
    capability_id: str
    confidence: float = Field(ge=0, le=1)
    rationale: str


class RequirementMappingProposalBatch(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    input_snapshot_hash: str
    instruction_version: str
    proposals: tuple[RequirementMappingProposal, ...]


class EvidenceCandidate(StrictContract):
    requirement_id: str
    product_version_id: str
    summary: str
    source_type: EvidenceSourceType
    authority_level: EvidenceAuthorityLevel
    valid_from: date
    valid_to: date | None = None
    relevance_score: float = Field(ge=0, le=1)
    sources: tuple[SourceReference, ...] = Field(min_length=1)


class EvidenceCandidateBatch(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    input_snapshot_hash: str
    retrieval_implementation_version: str
    requirement_id: str
    candidates: tuple[EvidenceCandidate, ...]


class ComplianceAssessmentDraft(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    requirement_id: str
    product_version_id: str
    assessment_as_of: date
    outcome: ComplianceOutcome
    evidence_span_ids: tuple[str, ...]
    confidence: float = Field(ge=0, le=1)
    risk: ReviewRisk
    rationale: str
    gaps: tuple[str, ...] = ()


class ConflictProposal(StrictContract):
    conflict_type: str
    severity: ReviewRisk
    participant_ids: tuple[str, ...] = Field(min_length=2)
    explanation: str


class ConflictDetectionBatch(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    input_snapshot_hash: str
    instruction_version: str
    conflicts: tuple[ConflictProposal, ...]


class CapabilityProposal(StrictContract):
    canonical_name: str
    description: str
    source: SourceReference
    confidence: float = Field(ge=0, le=1)


class CapabilityProposalBatch(StrictContract):
    schema_version: Literal["1.0"] = "1.0"
    product_version_id: str
    proposals: tuple[CapabilityProposal, ...]
