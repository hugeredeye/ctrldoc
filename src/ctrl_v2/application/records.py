from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class WorkspaceRecord:
    id: str
    name: str


@dataclass(frozen=True, slots=True)
class PrincipalRecord:
    id: str
    issuer: str
    subject: str
    principal_type: str
    active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class WorkspaceMembershipRecord:
    workspace_id: str
    principal_id: str
    role: str
    active: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BlockInsert:
    id: str
    ordinal: int
    block_type: str
    text: str
    page_no: int | None
    section_path: list[str]
    format_locator: dict[str, Any]
    text_hash: str


@dataclass(frozen=True, slots=True)
class DocumentUploadRecord:
    document_id: str
    version_id: str
    representation_id: str
    blocks: tuple[BlockRecord, ...]


@dataclass(frozen=True, slots=True)
class DocumentVersionRecord:
    id: str
    document_id: str
    object_key: str
    sha256: str
    media_type: str
    published_at: date | None


@dataclass(frozen=True, slots=True)
class RepresentationRecord:
    id: str
    document_version_id: str


@dataclass(frozen=True, slots=True)
class BlockRecord:
    id: str
    representation_id: str
    ordinal: int
    block_type: str
    text: str
    page_no: int | None
    section_path: list[str]
    format_locator: dict[str, Any]


@dataclass(frozen=True, slots=True)
class RfpRecord:
    id: str
    name: str
    source_document_version_id: str
    assessment_as_of: date
    status: str


@dataclass(frozen=True, slots=True)
class RequirementRecord:
    id: str
    rfp_id: str
    source_order: int
    atomic_text: str
    modality: str
    category: str | None
    confidence: float
    ambiguity_flags: list[str]
    status: str


@dataclass(frozen=True, slots=True)
class ProductRecord:
    id: str
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class ProductVersionRecord:
    id: str
    product_id: str
    version_label: str
    valid_from: date | None
    valid_to: date | None
    status: str


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    id: str
    canonical_key: str
    name: str
    description: str
    status: str


@dataclass(frozen=True, slots=True)
class CapabilityAssignmentRecord:
    id: str
    product_version_id: str
    capability_id: str
    valid_from: date | None
    valid_to: date | None
    approved: bool


@dataclass(frozen=True, slots=True)
class MappingRecord:
    id: str
    requirement_id: str
    product_version_id: str
    capability_id: str
    rationale: str
    confidence: float
    status: str


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    id: str
    requirement_id: str
    product_version_id: str
    source_type: str
    authority_level: str
    valid_from: date | None
    valid_to: date | None


@dataclass(frozen=True, slots=True)
class EvidenceSpanRecord:
    id: str
    evidence_id: str
    document_version_id: str
    representation_id: str
    document_block_id: str
    exact_quote: str
    format_locator: dict[str, Any]


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    id: str
    requirement_id: str
    product_version_id: str
    mapping_id: str
    outcome: str
    rationale: str
    confidence: float
    risk: str
    assessment_as_of: date
    status: str
    approved_at: datetime | None
    approved_by_principal_id: str | None
    revision: int


@dataclass(frozen=True, slots=True)
class DecisionEvidenceRecord:
    span: EvidenceSpanRecord
    evidence: EvidenceRecord


@dataclass(frozen=True, slots=True)
class SnapshotEvidenceRecord:
    evidence_span_id: str
    source_type: str
    authority_level: str
    document_version_id: str
    document_sha256: str
    locator: dict[str, Any]
    exact_quote: str
    valid_from: date | None
    valid_to: date | None


@dataclass(frozen=True, slots=True)
class SnapshotItemRecord:
    requirement: RequirementRecord
    decision: DecisionRecord
    product_version: ProductVersionRecord
    product: ProductRecord
    capability: CapabilityRecord
    evidence: tuple[SnapshotEvidenceRecord, ...]


@dataclass(frozen=True, slots=True)
class ResponseRecord:
    id: str
    rfp_id: str
    version_no: int
    assessment_as_of: date
    status: str
    snapshot_hash: str
    snapshot_json: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ExportRecord:
    id: str
    response_id: str
    format: str
    object_key: str
    sha256: str
    size_bytes: int
