from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Principal(Base):
    __tablename__ = "principals"
    __table_args__ = (
        UniqueConstraint("issuer", "subject"),
        CheckConstraint("principal_type IN ('USER', 'SERVICE')", name="principal_type_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(500))
    principal_type: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkspaceMembership(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('VIEWER', 'EDITOR', 'APPROVER', 'ADMIN')",
            name="workspace_membership_role_valid",
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    principal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("principals.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkspaceEntity:
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Document(WorkspaceEntity, Base):
    __tablename__ = "documents"

    title: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(32))
    original_filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")


class DocumentVersion(WorkspaceEntity, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["documents.workspace_id", "documents.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "document_id", "version_no"),
    )

    document_id: Mapped[str] = mapped_column(String(36))
    version_no: Mapped[int] = mapped_column(Integer)
    object_key: Mapped[str] = mapped_column(String(700), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String(160))
    size_bytes: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="RECEIVED")


class DocumentRepresentation(WorkspaceEntity, Base):
    __tablename__ = "document_representations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "document_version_id"],
            ["document_versions.workspace_id", "document_versions.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "workspace_id", "document_version_id", "parser_contract_version", "content_hash"
        ),
        UniqueConstraint("workspace_id", "id", "document_version_id"),
    )

    document_version_id: Mapped[str] = mapped_column(String(36))
    parser_contract_version: Mapped[str] = mapped_column(String(40))
    parser_build: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="PARSED")


class DocumentBlock(WorkspaceEntity, Base):
    __tablename__ = "document_blocks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "representation_id"],
            ["document_representations.workspace_id", "document_representations.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "representation_id", "ordinal"),
        UniqueConstraint("workspace_id", "id", "representation_id"),
    )

    representation_id: Mapped[str] = mapped_column(String(36))
    ordinal: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(String(40))
    text: Mapped[str] = mapped_column(Text)
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_path: Mapped[list[Any]] = mapped_column(JSON, default=list)
    format_locator: Mapped[dict[str, Any]] = mapped_column(JSON)
    text_hash: Mapped[str] = mapped_column(String(64))


class Rfp(WorkspaceEntity, Base):
    __tablename__ = "rfps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "source_document_version_id"],
            ["document_versions.workspace_id", "document_versions.id"],
        ),
    )

    name: Mapped[str] = mapped_column(String(300))
    source_document_version_id: Mapped[str] = mapped_column(String(36))
    assessment_as_of: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(40), default="DRAFT")
    requirements_baseline_revision: Mapped[int] = mapped_column(Integer, default=0)


class Requirement(WorkspaceEntity, Base):
    __tablename__ = "requirements"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "rfp_id"], ["rfps.workspace_id", "rfps.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("workspace_id", "rfp_id", "source_order"),
    )

    rfp_id: Mapped[str] = mapped_column(String(36))
    source_order: Mapped[int] = mapped_column(Integer)
    atomic_text: Mapped[str] = mapped_column(Text)
    modality: Mapped[str] = mapped_column(String(40), default="MUST")
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    acceptance_criteria: Mapped[list[Any]] = mapped_column(JSON, default=list)
    ambiguity_flags: Mapped[list[Any]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(32), default="ACCEPTED")


class RequirementSourceSpan(WorkspaceEntity, Base):
    __tablename__ = "requirement_source_spans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "requirement_id"],
            ["requirements.workspace_id", "requirements.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "document_block_id"],
            ["document_blocks.workspace_id", "document_blocks.id"],
        ),
    )

    requirement_id: Mapped[str] = mapped_column(String(36))
    document_block_id: Mapped[str] = mapped_column(String(36))
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    exact_quote: Mapped[str] = mapped_column(Text)
    quote_hash: Mapped[str] = mapped_column(String(64))


class Product(WorkspaceEntity, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    name: Mapped[str] = mapped_column(String(250))
    external_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")


class ProductVersion(WorkspaceEntity, Base):
    __tablename__ = "product_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "product_id"],
            ["products.workspace_id", "products.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "product_id", "version_label"),
    )

    product_id: Mapped[str] = mapped_column(String(36))
    version_label: Mapped[str] = mapped_column(String(120))
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")


class Capability(WorkspaceEntity, Base):
    __tablename__ = "capabilities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "parent_capability_id"],
            ["capabilities.workspace_id", "capabilities.id"],
        ),
        UniqueConstraint("workspace_id", "canonical_key"),
    )

    canonical_key: Mapped[str] = mapped_column(String(180))
    name: Mapped[str] = mapped_column(String(250))
    description: Mapped[str] = mapped_column(Text, default="")
    parent_capability_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")


class ProductVersionCapability(WorkspaceEntity, Base):
    __tablename__ = "product_version_capabilities"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "product_version_id"],
            ["product_versions.workspace_id", "product_versions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "capability_id"],
            ["capabilities.workspace_id", "capabilities.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("workspace_id", "product_version_id", "capability_id"),
    )

    product_version_id: Mapped[str] = mapped_column(String(36))
    capability_id: Mapped[str] = mapped_column(String(36))
    support_level: Mapped[str] = mapped_column(String(40), default="SUPPORTED")
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=True)


class ProductVersionDocument(WorkspaceEntity, Base):
    __tablename__ = "product_version_documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "product_version_id"],
            ["product_versions.workspace_id", "product_versions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "document_version_id"],
            ["document_versions.workspace_id", "document_versions.id"],
        ),
        UniqueConstraint("workspace_id", "product_version_id", "document_version_id"),
    )

    product_version_id: Mapped[str] = mapped_column(String(36))
    document_version_id: Mapped[str] = mapped_column(String(36))
    source_type: Mapped[str] = mapped_column(String(60))


class RequirementMapping(WorkspaceEntity, Base):
    __tablename__ = "requirement_mappings"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "requirement_id"],
            ["requirements.workspace_id", "requirements.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "product_version_id"],
            ["product_versions.workspace_id", "product_versions.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "capability_id"],
            ["capabilities.workspace_id", "capabilities.id"],
        ),
    )

    requirement_id: Mapped[str] = mapped_column(String(36))
    product_version_id: Mapped[str] = mapped_column(String(36))
    capability_id: Mapped[str] = mapped_column(String(36))
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), default="ACCEPTED")


class Evidence(WorkspaceEntity, Base):
    __tablename__ = "evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "requirement_id"],
            ["requirements.workspace_id", "requirements.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "product_version_id"],
            ["product_versions.workspace_id", "product_versions.id"],
        ),
    )

    requirement_id: Mapped[str] = mapped_column(String(36))
    product_version_id: Mapped[str] = mapped_column(String(36))
    summary: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(60))
    authority_level: Mapped[str] = mapped_column(String(32))
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="VERIFIED")
    retrieval_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EvidenceSpan(WorkspaceEntity, Base):
    __tablename__ = "evidence_spans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "evidence_id"],
            ["evidence.workspace_id", "evidence.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "document_version_id"],
            ["document_versions.workspace_id", "document_versions.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "representation_id"],
            ["document_representations.workspace_id", "document_representations.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "representation_id", "document_version_id"],
            [
                "document_representations.workspace_id",
                "document_representations.id",
                "document_representations.document_version_id",
            ],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "document_block_id"],
            ["document_blocks.workspace_id", "document_blocks.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "document_block_id", "representation_id"],
            [
                "document_blocks.workspace_id",
                "document_blocks.id",
                "document_blocks.representation_id",
            ],
        ),
    )

    evidence_id: Mapped[str] = mapped_column(String(36))
    document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    representation_id: Mapped[str] = mapped_column(String(36))
    document_block_id: Mapped[str] = mapped_column(String(36))
    start_offset: Mapped[int] = mapped_column(Integer)
    end_offset: Mapped[int] = mapped_column(Integer)
    exact_quote: Mapped[str] = mapped_column(Text)
    quote_hash: Mapped[str] = mapped_column(String(64))
    format_locator: Mapped[dict[str, Any]] = mapped_column(JSON)


class ComplianceDecision(WorkspaceEntity, Base):
    __tablename__ = "compliance_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "requirement_id"],
            ["requirements.workspace_id", "requirements.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "product_version_id"],
            ["product_versions.workspace_id", "product_versions.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "mapping_id"],
            ["requirement_mappings.workspace_id", "requirement_mappings.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "supersedes_id"],
            ["compliance_decisions.workspace_id", "compliance_decisions.id"],
        ),
    )

    requirement_id: Mapped[str] = mapped_column(String(36))
    product_version_id: Mapped[str] = mapped_column(String(36))
    mapping_id: Mapped[str] = mapped_column(String(36))
    outcome: Mapped[str] = mapped_column(String(40))
    rationale: Mapped[str] = mapped_column(Text)
    conditions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[Any]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float)
    risk: Mapped[str] = mapped_column(String(20))
    policy_required: Mapped[bool] = mapped_column(Boolean, default=False)
    assessment_as_of: Mapped[date] = mapped_column(Date)
    scope_valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    scope_valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_principal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("principals.id"), nullable=True
    )
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class DecisionEvidenceSpan(WorkspaceEntity, Base):
    __tablename__ = "decision_evidence_spans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "decision_id"],
            ["compliance_decisions.workspace_id", "compliance_decisions.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "evidence_span_id"],
            ["evidence_spans.workspace_id", "evidence_spans.id"],
        ),
        UniqueConstraint("workspace_id", "decision_id", "evidence_span_id"),
    )

    decision_id: Mapped[str] = mapped_column(String(36))
    evidence_span_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(32), default="SUPPORTS")


class Conflict(WorkspaceEntity, Base):
    __tablename__ = "conflicts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "requirement_id"],
            ["requirements.workspace_id", "requirements.id"],
            ondelete="CASCADE",
        ),
    )

    requirement_id: Mapped[str] = mapped_column(String(36))
    conflict_type: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20))
    explanation: Mapped[str] = mapped_column(Text)
    participant_ids: Mapped[list[Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="OPEN")


class HumanReview(WorkspaceEntity, Base):
    __tablename__ = "human_reviews"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "decision_id"],
            ["compliance_decisions.workspace_id", "compliance_decisions.id"],
            ondelete="CASCADE",
        ),
    )

    decision_id: Mapped[str] = mapped_column(String(36))
    risk: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(32))
    reviewer_principal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("principals.id"), nullable=False
    )
    comment: Mapped[str] = mapped_column(Text, default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Response(WorkspaceEntity, Base):
    __tablename__ = "responses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "rfp_id"], ["rfps.workspace_id", "rfps.id"], ondelete="CASCADE"
        ),
        UniqueConstraint("workspace_id", "rfp_id", "version_no"),
    )

    rfp_id: Mapped[str] = mapped_column(String(36))
    version_no: Mapped[int] = mapped_column(Integer)
    assessment_as_of: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="SNAPSHOT")
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class ResponseItem(WorkspaceEntity, Base):
    __tablename__ = "response_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "response_id"],
            ["responses.workspace_id", "responses.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "requirement_id"],
            ["requirements.workspace_id", "requirements.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "decision_id"],
            ["compliance_decisions.workspace_id", "compliance_decisions.id"],
        ),
        UniqueConstraint("workspace_id", "response_id", "source_order"),
    )

    response_id: Mapped[str] = mapped_column(String(36))
    requirement_id: Mapped[str] = mapped_column(String(36))
    decision_id: Mapped[str] = mapped_column(String(36))
    source_order: Mapped[int] = mapped_column(Integer)
    item_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class ResponseExport(WorkspaceEntity, Base):
    __tablename__ = "response_exports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "response_id"],
            ["responses.workspace_id", "responses.id"],
            ondelete="CASCADE",
        ),
    )

    response_id: Mapped[str] = mapped_column(String(36))
    format: Mapped[str] = mapped_column(String(20), default="XLSX")
    object_key: Mapped[str] = mapped_column(String(700), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer)


class ProcessingJob(WorkspaceEntity, Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (UniqueConstraint("workspace_id", "idempotency_key"),)

    job_type: Mapped[str] = mapped_column(String(80))
    subject_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    idempotency_key: Mapped[str] = mapped_column(String(200))
    input_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class OutboxEvent(WorkspaceEntity, Base):
    __tablename__ = "outbox_events"

    event_type: Mapped[str] = mapped_column(String(120))
    aggregate_id: Mapped[str] = mapped_column(String(36))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvaluationDataset(WorkspaceEntity, Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (UniqueConstraint("workspace_id", "name", "version"),)

    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(80))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")


class EvaluationRun(WorkspaceEntity, Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "dataset_id"],
            ["evaluation_datasets.workspace_id", "evaluation_datasets.id"],
        ),
    )

    dataset_id: Mapped[str] = mapped_column(String(36))
    implementation_versions: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
