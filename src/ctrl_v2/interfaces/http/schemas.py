from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from ctrl_v2.domain.enums import (
    ComplianceOutcome,
    DocumentKind,
    EvidenceAuthorityLevel,
    EvidenceSourceType,
    WorkspaceRole,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorkspaceCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)


class RfpCreate(ApiModel):
    name: str = Field(min_length=1, max_length=300)
    source_document_version_id: str
    assessment_as_of: date


class RequirementCreate(ApiModel):
    rfp_id: str
    source_order: int = Field(ge=1)
    atomic_text: str = Field(min_length=1)
    modality: str = "MUST"
    category: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    ambiguity_flags: list[str] = []
    document_block_id: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)


class ProductCreate(ApiModel):
    name: str = Field(min_length=1, max_length=250)


class ProductVersionCreate(ApiModel):
    version_label: str = Field(min_length=1, max_length=120)
    valid_from: date
    valid_to: date | None = None


class CapabilityCreate(ApiModel):
    canonical_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$", max_length=180)
    name: str = Field(min_length=1, max_length=250)
    description: str = ""


class CapabilityAssignmentCreate(ApiModel):
    capability_id: str
    valid_from: date
    valid_to: date | None = None


class ProductVersionDocumentCreate(ApiModel):
    document_version_id: str
    source_type: EvidenceSourceType


class MappingCreate(ApiModel):
    requirement_id: str
    product_version_id: str
    capability_id: str
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class EvidenceSpanCreate(ApiModel):
    requirement_id: str
    product_version_id: str
    summary: str = Field(min_length=1)
    source_type: EvidenceSourceType
    authority_level: EvidenceAuthorityLevel
    valid_from: date
    valid_to: date | None = None
    document_version_id: str
    document_block_id: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)


class DecisionCreate(ApiModel):
    mapping_id: str
    outcome: ComplianceOutcome
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    evidence_span_ids: list[str] = []
    policy_required: bool = False


class DecisionUpdate(ApiModel):
    rationale: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ApprovalCreate(ApiModel):
    comment: str = ""


class BatchApprovalCreate(ApprovalCreate):
    decision_ids: list[str] = Field(min_length=1)


class MembershipCreate(ApiModel):
    principal_id: str
    role: WorkspaceRole


class MembershipUpdate(ApiModel):
    role: WorkspaceRole | None = None
    active: bool | None = None


class ReviewCreate(ApiModel):
    comment: str = ""


class ResponseCreate(ApiModel):
    rfp_id: str
    decision_ids: list[str] = Field(min_length=1)


class DocumentUploadMetadata(ApiModel):
    title: str
    kind: DocumentKind
    published_at: date | None = None
