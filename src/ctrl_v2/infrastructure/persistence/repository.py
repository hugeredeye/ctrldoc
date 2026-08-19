from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, TypeVar

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ctrl_v2.application.records import (
    BlockInsert,
    BlockRecord,
    CapabilityAssignmentRecord,
    CapabilityRecord,
    DecisionEvidenceRecord,
    DecisionRecord,
    DocumentUploadRecord,
    DocumentVersionRecord,
    EvidenceRecord,
    EvidenceSpanRecord,
    ExportRecord,
    MappingRecord,
    PrincipalRecord,
    ProductRecord,
    ProductVersionRecord,
    RepresentationRecord,
    RequirementRecord,
    ResponseRecord,
    RfpRecord,
    SnapshotEvidenceRecord,
    SnapshotItemRecord,
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)
from ctrl_v2.domain.exceptions import ConflictError, NotFoundError

from .models import (
    Capability,
    ComplianceDecision,
    Conflict,
    DecisionEvidenceSpan,
    Document,
    DocumentBlock,
    DocumentRepresentation,
    DocumentVersion,
    Evidence,
    EvidenceSpan,
    HumanReview,
    Principal,
    Product,
    ProductVersion,
    ProductVersionCapability,
    ProductVersionDocument,
    Requirement,
    RequirementMapping,
    RequirementSourceSpan,
    Response,
    ResponseExport,
    ResponseItem,
    Rfp,
    Workspace,
    WorkspaceMembership,
    new_id,
    utcnow,
)

OrmT = TypeVar("OrmT")


class SqlAlchemyStage1Repository:
    """SQLAlchemy implementation of the application repository port."""

    def __init__(self, session: Session, workspace_id: str | None) -> None:
        self.session = session
        self.workspace_id = workspace_id

    def _tenant_id(self) -> str:
        if self.workspace_id is None:
            raise RuntimeError("A workspace-scoped repository operation requires workspace context")
        return self.workspace_id

    def _get(self, model: type[OrmT], entity_id: str) -> OrmT | None:
        return self.session.get(model, (self._tenant_id(), entity_id))

    @staticmethod
    def _required(value: OrmT | None, entity_name: str) -> OrmT:
        if value is None:
            raise NotFoundError(f"{entity_name} was not found")
        return value

    def get_or_create_principal(
        self, issuer: str, subject: str, principal_type: str
    ) -> PrincipalRecord:
        principal_id = new_id()
        created_at = utcnow()
        self.session.execute(
            insert(Principal)
            .values(
                id=principal_id,
                issuer=issuer,
                subject=subject,
                principal_type=principal_type,
                active=True,
                created_at=created_at,
            )
            .on_conflict_do_nothing(index_elements=[Principal.issuer, Principal.subject])
        )
        row = self.session.scalar(
            select(Principal).where(Principal.issuer == issuer, Principal.subject == subject)
        )
        return self._principal(self._required(row, "Principal"))

    def get_principal(self, principal_id: str) -> PrincipalRecord | None:
        row = self.session.get(Principal, principal_id)
        return self._principal(row) if row else None

    def create_workspace(
        self, workspace_id: str, name: str, initial_admin_principal_id: str
    ) -> WorkspaceRecord:
        if self._tenant_id() != workspace_id:
            raise RuntimeError("Workspace creation requires matching database context")
        row = Workspace(id=workspace_id, name=name)
        self.session.add(row)
        self.session.add(
            WorkspaceMembership(
                workspace_id=workspace_id,
                principal_id=initial_admin_principal_id,
                role="ADMIN",
                active=True,
            )
        )
        self.session.flush()
        return self._workspace(row)

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        row = self.session.get(Workspace, workspace_id)
        return self._workspace(row) if row else None

    def get_membership(self, principal_id: str) -> WorkspaceMembershipRecord | None:
        row = self.session.get(WorkspaceMembership, (self._tenant_id(), principal_id))
        return self._membership(row) if row else None

    def create_membership(self, principal_id: str, role: str) -> WorkspaceMembershipRecord:
        if self.get_membership(principal_id) is not None:
            raise ConflictError("Workspace membership already exists")
        row = WorkspaceMembership(
            workspace_id=self._tenant_id(),
            principal_id=principal_id,
            role=role,
            active=True,
        )
        self.session.add(row)
        self.session.flush()
        return self._membership(row)

    def update_membership(
        self, principal_id: str, role: str | None, active: bool | None
    ) -> WorkspaceMembershipRecord:
        row = self._required(
            self.session.get(WorkspaceMembership, (self._tenant_id(), principal_id)),
            "WorkspaceMembership",
        )
        if role is not None:
            row.role = role
        if active is not None:
            row.active = active
        self.session.flush()
        return self._membership(row)

    def list_memberships(self) -> list[WorkspaceMembershipRecord]:
        rows = self.session.scalars(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == self._tenant_id())
            .order_by(WorkspaceMembership.created_at, WorkspaceMembership.principal_id)
        )
        return [self._membership(row) for row in rows]

    def create_document_bundle(
        self,
        *,
        document_id: str,
        version_id: str,
        representation_id: str,
        title: str,
        kind: str,
        original_filename: str,
        object_key: str,
        sha256: str,
        media_type: str,
        size_bytes: int,
        published_at: date | None,
        parser_contract_version: str,
        parser_build: str,
        content_hash: str,
        blocks: Sequence[BlockInsert],
    ) -> DocumentUploadRecord:
        workspace_id = self._tenant_id()
        self.session.add(
            Document(
                workspace_id=workspace_id,
                id=document_id,
                title=title,
                kind=kind,
                original_filename=original_filename,
                status="ACTIVE",
            )
        )
        self.session.flush()
        self.session.add(
            DocumentVersion(
                workspace_id=workspace_id,
                id=version_id,
                document_id=document_id,
                version_no=1,
                object_key=object_key,
                sha256=sha256,
                media_type=media_type,
                size_bytes=size_bytes,
                published_at=published_at,
                processing_status="PARSED",
            )
        )
        self.session.flush()
        self.session.add(
            DocumentRepresentation(
                workspace_id=workspace_id,
                id=representation_id,
                document_version_id=version_id,
                parser_contract_version=parser_contract_version,
                parser_build=parser_build,
                content_hash=content_hash,
                status="PARSED",
            )
        )
        self.session.flush()
        rows = []
        for block in blocks:
            row = DocumentBlock(
                workspace_id=workspace_id,
                id=block.id,
                representation_id=representation_id,
                ordinal=block.ordinal,
                block_type=block.block_type,
                text=block.text,
                page_no=block.page_no,
                section_path=block.section_path,
                format_locator=block.format_locator,
                text_hash=block.text_hash,
            )
            self.session.add(row)
            rows.append(row)
        self.session.flush()
        return DocumentUploadRecord(
            document_id=document_id,
            version_id=version_id,
            representation_id=representation_id,
            blocks=tuple(self._block(row) for row in rows),
        )

    def get_document_version(self, version_id: str) -> DocumentVersionRecord | None:
        row = self._get(DocumentVersion, version_id)
        return self._document_version(row) if row else None

    def get_representation(self, representation_id: str) -> RepresentationRecord | None:
        row = self._get(DocumentRepresentation, representation_id)
        return self._representation(row) if row else None

    def get_block(self, block_id: str) -> BlockRecord | None:
        row = self._get(DocumentBlock, block_id)
        return self._block(row) if row else None

    def create_rfp(
        self, name: str, source_document_version_id: str, assessment_as_of: date
    ) -> RfpRecord:
        row = Rfp(
            workspace_id=self._tenant_id(),
            name=name,
            source_document_version_id=source_document_version_id,
            assessment_as_of=assessment_as_of,
            status="MANUAL_ASSESSMENT",
        )
        self.session.add(row)
        self.session.flush()
        return self._rfp(row)

    def get_rfp(self, rfp_id: str) -> RfpRecord | None:
        row = self._get(Rfp, rfp_id)
        return self._rfp(row) if row else None

    def create_requirement(
        self,
        *,
        rfp_id: str,
        source_order: int,
        atomic_text: str,
        modality: str,
        category: str | None,
        confidence: float,
        ambiguity_flags: list[str],
        document_block_id: str,
        start_offset: int,
        end_offset: int,
        exact_quote: str,
        quote_hash: str,
    ) -> RequirementRecord:
        workspace_id = self._tenant_id()
        row = Requirement(
            workspace_id=workspace_id,
            rfp_id=rfp_id,
            source_order=source_order,
            atomic_text=atomic_text,
            modality=modality,
            category=category,
            acceptance_criteria=[],
            ambiguity_flags=ambiguity_flags,
            confidence=confidence,
            status="ACCEPTED",
        )
        self.session.add(row)
        self.session.flush()
        self.session.add(
            RequirementSourceSpan(
                workspace_id=workspace_id,
                requirement_id=row.id,
                document_block_id=document_block_id,
                start_offset=start_offset,
                end_offset=end_offset,
                exact_quote=exact_quote,
                quote_hash=quote_hash,
            )
        )
        return self._requirement(row)

    def get_requirement(self, requirement_id: str) -> RequirementRecord | None:
        row = self._get(Requirement, requirement_id)
        return self._requirement(row) if row else None

    def list_accepted_requirements(self, rfp_id: str) -> list[RequirementRecord]:
        rows = self.session.scalars(
            select(Requirement)
            .where(
                Requirement.workspace_id == self._tenant_id(),
                Requirement.rfp_id == rfp_id,
                Requirement.status == "ACCEPTED",
            )
            .order_by(Requirement.source_order, Requirement.id)
        )
        return [self._requirement(row) for row in rows]

    def create_product(self, name: str) -> ProductRecord:
        row = Product(workspace_id=self._tenant_id(), name=name, status="ACTIVE")
        self.session.add(row)
        self.session.flush()
        return self._product(row)

    def get_product(self, product_id: str) -> ProductRecord | None:
        row = self._get(Product, product_id)
        return self._product(row) if row else None

    def create_product_version(
        self,
        product_id: str,
        version_label: str,
        valid_from: date,
        valid_to: date | None,
    ) -> ProductVersionRecord:
        row = ProductVersion(
            workspace_id=self._tenant_id(),
            product_id=product_id,
            version_label=version_label,
            valid_from=valid_from,
            valid_to=valid_to,
            status="ACTIVE",
        )
        self.session.add(row)
        self.session.flush()
        return self._product_version(row)

    def get_product_version(self, version_id: str) -> ProductVersionRecord | None:
        row = self._get(ProductVersion, version_id)
        return self._product_version(row) if row else None

    def create_capability(
        self, canonical_key: str, name: str, description: str
    ) -> CapabilityRecord:
        row = Capability(
            workspace_id=self._tenant_id(),
            canonical_key=canonical_key,
            name=name,
            description=description,
            status="ACTIVE",
        )
        self.session.add(row)
        self.session.flush()
        return self._capability(row)

    def get_capability(self, capability_id: str) -> CapabilityRecord | None:
        row = self._get(Capability, capability_id)
        return self._capability(row) if row else None

    def create_capability_assignment(
        self,
        product_version_id: str,
        capability_id: str,
        valid_from: date,
        valid_to: date | None,
    ) -> CapabilityAssignmentRecord:
        row = ProductVersionCapability(
            workspace_id=self._tenant_id(),
            product_version_id=product_version_id,
            capability_id=capability_id,
            valid_from=valid_from,
            valid_to=valid_to,
            approved=True,
        )
        self.session.add(row)
        self.session.flush()
        return self._assignment(row)

    def get_capability_assignment(
        self, product_version_id: str, capability_id: str
    ) -> CapabilityAssignmentRecord | None:
        row = self.session.scalar(
            select(ProductVersionCapability).where(
                ProductVersionCapability.workspace_id == self._tenant_id(),
                ProductVersionCapability.product_version_id == product_version_id,
                ProductVersionCapability.capability_id == capability_id,
                ProductVersionCapability.approved.is_(True),
            )
        )
        return self._assignment(row) if row else None

    def create_mapping(
        self,
        requirement_id: str,
        product_version_id: str,
        capability_id: str,
        rationale: str,
        confidence: float,
    ) -> MappingRecord:
        row = RequirementMapping(
            workspace_id=self._tenant_id(),
            requirement_id=requirement_id,
            product_version_id=product_version_id,
            capability_id=capability_id,
            rationale=rationale,
            confidence=confidence,
            status="ACCEPTED",
        )
        self.session.add(row)
        self.session.flush()
        return self._mapping(row)

    def get_mapping(self, mapping_id: str) -> MappingRecord | None:
        row = self._get(RequirementMapping, mapping_id)
        return self._mapping(row) if row else None

    def attach_product_document(
        self, product_version_id: str, document_version_id: str, source_type: str
    ) -> dict[str, Any]:
        row = ProductVersionDocument(
            workspace_id=self._tenant_id(),
            product_version_id=product_version_id,
            document_version_id=document_version_id,
            source_type=source_type,
        )
        self.session.add(row)
        self.session.flush()
        return {
            "id": row.id,
            "product_version_id": row.product_version_id,
            "document_version_id": row.document_version_id,
            "source_type": row.source_type,
        }

    def product_document_exists(
        self, product_version_id: str, document_version_id: str, source_type: str
    ) -> bool:
        return (
            self.session.scalar(
                select(ProductVersionDocument.id).where(
                    ProductVersionDocument.workspace_id == self._tenant_id(),
                    ProductVersionDocument.product_version_id == product_version_id,
                    ProductVersionDocument.document_version_id == document_version_id,
                    ProductVersionDocument.source_type == source_type,
                )
            )
            is not None
        )

    def create_evidence_span(
        self,
        *,
        requirement_id: str,
        product_version_id: str,
        summary: str,
        source_type: str,
        authority_level: str,
        valid_from: date,
        valid_to: date | None,
        document_version_id: str,
        representation_id: str,
        document_block_id: str,
        start_offset: int,
        end_offset: int,
        exact_quote: str,
        quote_hash: str,
        format_locator: dict[str, Any],
        supersedes_evidence_id: str | None,
        created_by_principal_id: str,
    ) -> tuple[EvidenceRecord, EvidenceSpanRecord]:
        workspace_id = self._tenant_id()
        evidence = Evidence(
            workspace_id=workspace_id,
            requirement_id=requirement_id,
            product_version_id=product_version_id,
            summary=summary,
            source_type=source_type,
            authority_level=authority_level,
            valid_from=valid_from,
            valid_to=valid_to,
            status="VERIFIED",
            supersedes_id=supersedes_evidence_id,
            created_by_principal_id=created_by_principal_id,
        )
        self.session.add(evidence)
        self.session.flush()
        span = EvidenceSpan(
            workspace_id=workspace_id,
            evidence_id=evidence.id,
            document_version_id=document_version_id,
            representation_id=representation_id,
            document_block_id=document_block_id,
            start_offset=start_offset,
            end_offset=end_offset,
            exact_quote=exact_quote,
            quote_hash=quote_hash,
            format_locator=format_locator,
        )
        self.session.add(span)
        self.session.flush()
        return self._evidence(evidence), self._span(span)

    def get_evidence_span(self, span_id: str) -> EvidenceSpanRecord | None:
        row = self._get(EvidenceSpan, span_id)
        return self._span(row) if row else None

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        row = self._get(Evidence, evidence_id)
        return self._evidence(row) if row else None

    def count_open_conflicts(self, requirement_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(Conflict.id)).where(
                    Conflict.workspace_id == self._tenant_id(),
                    Conflict.requirement_id == requirement_id,
                    Conflict.status.in_(["OPEN", "CONFIRMED"]),
                )
            )
            or 0
        )

    def create_decision(
        self,
        *,
        requirement_id: str,
        product_version_id: str,
        mapping_id: str,
        outcome: str,
        rationale: str,
        confidence: float,
        risk: str,
        policy_required: bool,
        assessment_as_of: date,
        evidence_span_ids: Sequence[str],
    ) -> DecisionRecord:
        workspace_id = self._tenant_id()
        row = ComplianceDecision(
            workspace_id=workspace_id,
            requirement_id=requirement_id,
            product_version_id=product_version_id,
            mapping_id=mapping_id,
            outcome=outcome,
            rationale=rationale,
            conditions=[],
            gaps=[],
            confidence=confidence,
            risk=risk,
            policy_required=policy_required,
            assessment_as_of=assessment_as_of,
            scope_valid_from=assessment_as_of,
            scope_valid_to=assessment_as_of,
            status="DRAFT",
        )
        self.session.add(row)
        self.session.flush()
        for span_id in evidence_span_ids:
            self.session.add(
                DecisionEvidenceSpan(
                    workspace_id=workspace_id,
                    decision_id=row.id,
                    evidence_span_id=span_id,
                    role="SUPPORTS",
                )
            )
        return self._decision(row)

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        row = self._get(ComplianceDecision, decision_id)
        return self._decision(row) if row else None

    def list_decision_evidence(self, decision_id: str) -> list[DecisionEvidenceRecord]:
        rows = self.session.execute(
            select(EvidenceSpan, Evidence)
            .join(
                DecisionEvidenceSpan,
                (DecisionEvidenceSpan.workspace_id == EvidenceSpan.workspace_id)
                & (DecisionEvidenceSpan.evidence_span_id == EvidenceSpan.id),
            )
            .join(
                Evidence,
                (Evidence.workspace_id == EvidenceSpan.workspace_id)
                & (Evidence.id == EvidenceSpan.evidence_id),
            )
            .where(
                DecisionEvidenceSpan.workspace_id == self._tenant_id(),
                DecisionEvidenceSpan.decision_id == decision_id,
            )
        )
        return [
            DecisionEvidenceRecord(span=self._span(span), evidence=self._evidence(evidence))
            for span, evidence in rows
        ]

    def list_decision_span_ids(self, decision_id: str) -> list[str]:
        return list(
            self.session.scalars(
                select(DecisionEvidenceSpan.evidence_span_id).where(
                    DecisionEvidenceSpan.workspace_id == self._tenant_id(),
                    DecisionEvidenceSpan.decision_id == decision_id,
                )
            )
        )

    def update_draft_decision(
        self, decision_id: str, rationale: str | None, confidence: float | None
    ) -> DecisionRecord:
        row = self._required(self._get(ComplianceDecision, decision_id), "ComplianceDecision")
        if rationale is not None:
            row.rationale = rationale
        if confidence is not None:
            row.confidence = confidence
        row.revision += 1
        self.session.flush()
        return self._decision(row)

    def approve_decision(
        self,
        decision_id: str,
        approved_at: datetime,
        reviewer_principal_id: str,
        comment: str,
        review_mode: str,
    ) -> DecisionRecord:
        row = self._required(self._get(ComplianceDecision, decision_id), "ComplianceDecision")
        row.status = "APPROVED"
        row.approved_at = approved_at
        row.approved_by_principal_id = reviewer_principal_id
        self.session.add(
            HumanReview(
                workspace_id=self._tenant_id(),
                decision_id=row.id,
                risk=row.risk,
                mode=review_mode,
                status="APPROVED",
                reviewer_principal_id=reviewer_principal_id,
                comment=comment,
            )
        )
        self.session.flush()
        return self._decision(row)

    def record_decision_review(
        self,
        decision_id: str,
        *,
        decision_status: str,
        review_status: str,
        reviewer_principal_id: str,
        comment: str,
        review_mode: str,
    ) -> DecisionRecord:
        row = self._required(self._get(ComplianceDecision, decision_id), "ComplianceDecision")
        row.status = decision_status
        self.session.add(
            HumanReview(
                workspace_id=self._tenant_id(),
                decision_id=row.id,
                risk=row.risk,
                mode=review_mode,
                status=review_status,
                reviewer_principal_id=reviewer_principal_id,
                comment=comment,
            )
        )
        self.session.flush()
        return self._decision(row)

    def next_response_version(self, rfp_id: str) -> int:
        return (
            int(
                self.session.scalar(
                    select(func.count(Response.id)).where(
                        Response.workspace_id == self._tenant_id(), Response.rfp_id == rfp_id
                    )
                )
                or 0
            )
            + 1
        )

    def get_snapshot_item(self, decision_id: str) -> SnapshotItemRecord:
        decision_row = self._required(
            self._get(ComplianceDecision, decision_id), "ComplianceDecision"
        )
        requirement_row = self._required(
            self._get(Requirement, decision_row.requirement_id), "Requirement"
        )
        mapping_row = self._required(
            self._get(RequirementMapping, decision_row.mapping_id), "RequirementMapping"
        )
        version_row = self._required(
            self._get(ProductVersion, mapping_row.product_version_id), "ProductVersion"
        )
        product_row = self._required(self._get(Product, version_row.product_id), "Product")
        capability_row = self._required(
            self._get(Capability, mapping_row.capability_id), "Capability"
        )
        evidence_rows = self.session.execute(
            select(EvidenceSpan, Evidence, DocumentVersion)
            .join(
                DecisionEvidenceSpan,
                (DecisionEvidenceSpan.workspace_id == EvidenceSpan.workspace_id)
                & (DecisionEvidenceSpan.evidence_span_id == EvidenceSpan.id),
            )
            .join(
                Evidence,
                (Evidence.workspace_id == EvidenceSpan.workspace_id)
                & (Evidence.id == EvidenceSpan.evidence_id),
            )
            .join(
                DocumentVersion,
                (DocumentVersion.workspace_id == EvidenceSpan.workspace_id)
                & (DocumentVersion.id == EvidenceSpan.document_version_id),
            )
            .where(
                DecisionEvidenceSpan.workspace_id == self._tenant_id(),
                DecisionEvidenceSpan.decision_id == decision_id,
            )
            .order_by(EvidenceSpan.id)
        )
        return SnapshotItemRecord(
            requirement=self._requirement(requirement_row),
            decision=self._decision(decision_row),
            product_version=self._product_version(version_row),
            product=self._product(product_row),
            capability=self._capability(capability_row),
            evidence=tuple(
                SnapshotEvidenceRecord(
                    evidence_id=evidence.id,
                    evidence_span_id=span.id,
                    source_type=evidence.source_type,
                    authority_level=evidence.authority_level,
                    document_version_id=span.document_version_id,
                    document_object_key=document_version.object_key,
                    document_sha256=document_version.sha256,
                    document_size_bytes=document_version.size_bytes,
                    locator=dict(span.format_locator),
                    exact_quote=span.exact_quote,
                    valid_from=evidence.valid_from,
                    valid_to=evidence.valid_to,
                )
                for span, evidence, document_version in evidence_rows
            ),
        )

    def create_response(
        self,
        *,
        response_id: str,
        rfp_id: str,
        version_no: int,
        assessment_as_of: date,
        snapshot_hash: str,
        snapshot_json: dict[str, Any],
    ) -> ResponseRecord:
        workspace_id = self._tenant_id()
        row = Response(
            workspace_id=workspace_id,
            id=response_id,
            rfp_id=rfp_id,
            version_no=version_no,
            assessment_as_of=assessment_as_of,
            status="SNAPSHOT",
            snapshot_hash=snapshot_hash,
            snapshot_json=snapshot_json,
        )
        self.session.add(row)
        self.session.flush()
        for item in snapshot_json["items"]:
            self.session.add(
                ResponseItem(
                    workspace_id=workspace_id,
                    response_id=response_id,
                    requirement_id=item["requirement_id"],
                    decision_id=item["decision_id"],
                    source_order=item["source_order"],
                    item_json=item,
                )
            )
        return self._response(row)

    def get_response(self, response_id: str) -> ResponseRecord | None:
        row = self._get(Response, response_id)
        return self._response(row) if row else None

    def get_response_export(self, response_id: str) -> ExportRecord | None:
        row = self.session.scalar(
            select(ResponseExport).where(
                ResponseExport.workspace_id == self._tenant_id(),
                ResponseExport.response_id == response_id,
            )
        )
        return self._export(row) if row else None

    def create_response_export(
        self,
        *,
        response_id: str,
        format: str,
        object_key: str,
        sha256: str,
        size_bytes: int,
    ) -> ExportRecord:
        row = ResponseExport(
            workspace_id=self._tenant_id(),
            response_id=response_id,
            format=format,
            object_key=object_key,
            sha256=sha256,
            size_bytes=size_bytes,
        )
        self.session.add(row)
        self.session.flush()
        return self._export(row)

    def get_export(self, export_id: str) -> ExportRecord | None:
        row = self._get(ResponseExport, export_id)
        return self._export(row) if row else None

    @staticmethod
    def _workspace(row: Workspace) -> WorkspaceRecord:
        return WorkspaceRecord(row.id, row.name)

    @staticmethod
    def _principal(row: Principal) -> PrincipalRecord:
        return PrincipalRecord(
            row.id,
            row.issuer,
            row.subject,
            row.principal_type,
            row.active,
            row.created_at,
        )

    @staticmethod
    def _membership(row: WorkspaceMembership) -> WorkspaceMembershipRecord:
        return WorkspaceMembershipRecord(
            row.workspace_id,
            row.principal_id,
            row.role,
            row.active,
            row.created_at,
        )

    @staticmethod
    def _document_version(row: DocumentVersion) -> DocumentVersionRecord:
        return DocumentVersionRecord(
            row.id,
            row.document_id,
            row.object_key,
            row.sha256,
            row.size_bytes,
            row.media_type,
            row.published_at,
        )

    @staticmethod
    def _representation(row: DocumentRepresentation) -> RepresentationRecord:
        return RepresentationRecord(row.id, row.document_version_id)

    @staticmethod
    def _block(row: DocumentBlock) -> BlockRecord:
        return BlockRecord(
            row.id,
            row.representation_id,
            row.ordinal,
            row.block_type,
            row.text,
            row.page_no,
            list(row.section_path),
            dict(row.format_locator),
        )

    @staticmethod
    def _rfp(row: Rfp) -> RfpRecord:
        return RfpRecord(
            row.id,
            row.name,
            row.source_document_version_id,
            row.assessment_as_of,
            row.status,
        )

    @staticmethod
    def _requirement(row: Requirement) -> RequirementRecord:
        return RequirementRecord(
            row.id,
            row.rfp_id,
            row.source_order,
            row.atomic_text,
            row.modality,
            row.category,
            row.confidence,
            list(row.ambiguity_flags),
            row.status,
        )

    @staticmethod
    def _product(row: Product) -> ProductRecord:
        return ProductRecord(row.id, row.name, row.status)

    @staticmethod
    def _product_version(row: ProductVersion) -> ProductVersionRecord:
        return ProductVersionRecord(
            row.id,
            row.product_id,
            row.version_label,
            row.valid_from,
            row.valid_to,
            row.status,
        )

    @staticmethod
    def _capability(row: Capability) -> CapabilityRecord:
        return CapabilityRecord(row.id, row.canonical_key, row.name, row.description, row.status)

    @staticmethod
    def _assignment(row: ProductVersionCapability) -> CapabilityAssignmentRecord:
        return CapabilityAssignmentRecord(
            row.id,
            row.product_version_id,
            row.capability_id,
            row.valid_from,
            row.valid_to,
            row.approved,
        )

    @staticmethod
    def _mapping(row: RequirementMapping) -> MappingRecord:
        return MappingRecord(
            row.id,
            row.requirement_id,
            row.product_version_id,
            row.capability_id,
            row.rationale,
            row.confidence,
            row.status,
        )

    @staticmethod
    def _evidence(row: Evidence) -> EvidenceRecord:
        return EvidenceRecord(
            row.id,
            row.requirement_id,
            row.product_version_id,
            row.source_type,
            row.authority_level,
            row.valid_from,
            row.valid_to,
            row.supersedes_id,
            row.created_by_principal_id,
        )

    @staticmethod
    def _span(row: EvidenceSpan) -> EvidenceSpanRecord:
        return EvidenceSpanRecord(
            row.id,
            row.evidence_id,
            row.document_version_id,
            row.representation_id,
            row.document_block_id,
            row.exact_quote,
            dict(row.format_locator),
        )

    @staticmethod
    def _decision(row: ComplianceDecision) -> DecisionRecord:
        return DecisionRecord(
            row.id,
            row.requirement_id,
            row.product_version_id,
            row.mapping_id,
            row.outcome,
            row.rationale,
            row.confidence,
            row.risk,
            row.assessment_as_of,
            row.status,
            row.approved_at,
            row.approved_by_principal_id,
            row.revision,
        )

    @staticmethod
    def _response(row: Response) -> ResponseRecord:
        return ResponseRecord(
            row.id,
            row.rfp_id,
            row.version_no,
            row.assessment_as_of,
            row.status,
            row.snapshot_hash,
            dict(row.snapshot_json),
        )

    @staticmethod
    def _export(row: ResponseExport) -> ExportRecord:
        return ExportRecord(
            row.id,
            row.response_id,
            row.format,
            row.object_key,
            row.sha256,
            row.size_bytes,
        )
