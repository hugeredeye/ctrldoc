from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any, Protocol

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
    SnapshotItemRecord,
    WorkspaceMembershipRecord,
    WorkspaceRecord,
)


class Stage1Repository(Protocol):
    def get_or_create_principal(
        self, issuer: str, subject: str, principal_type: str
    ) -> PrincipalRecord: ...

    def get_principal(self, principal_id: str) -> PrincipalRecord | None: ...

    def create_workspace(
        self, workspace_id: str, name: str, initial_admin_principal_id: str
    ) -> WorkspaceRecord: ...

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None: ...

    def get_membership(self, principal_id: str) -> WorkspaceMembershipRecord | None: ...

    def create_membership(
        self, principal_id: str, role: str
    ) -> WorkspaceMembershipRecord: ...

    def update_membership(
        self, principal_id: str, role: str | None, active: bool | None
    ) -> WorkspaceMembershipRecord: ...

    def list_memberships(self) -> list[WorkspaceMembershipRecord]: ...

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
    ) -> DocumentUploadRecord: ...

    def get_document_version(self, version_id: str) -> DocumentVersionRecord | None: ...

    def get_representation(self, representation_id: str) -> RepresentationRecord | None: ...

    def get_block(self, block_id: str) -> BlockRecord | None: ...

    def create_rfp(
        self, name: str, source_document_version_id: str, assessment_as_of: date
    ) -> RfpRecord: ...

    def get_rfp(self, rfp_id: str) -> RfpRecord | None: ...

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
    ) -> RequirementRecord: ...

    def get_requirement(self, requirement_id: str) -> RequirementRecord | None: ...

    def list_accepted_requirements(self, rfp_id: str) -> list[RequirementRecord]: ...

    def create_product(self, name: str) -> ProductRecord: ...

    def get_product(self, product_id: str) -> ProductRecord | None: ...

    def create_product_version(
        self,
        product_id: str,
        version_label: str,
        valid_from: date,
        valid_to: date | None,
    ) -> ProductVersionRecord: ...

    def get_product_version(self, version_id: str) -> ProductVersionRecord | None: ...

    def create_capability(
        self, canonical_key: str, name: str, description: str
    ) -> CapabilityRecord: ...

    def get_capability(self, capability_id: str) -> CapabilityRecord | None: ...

    def create_capability_assignment(
        self,
        product_version_id: str,
        capability_id: str,
        valid_from: date,
        valid_to: date | None,
    ) -> CapabilityAssignmentRecord: ...

    def get_capability_assignment(
        self, product_version_id: str, capability_id: str
    ) -> CapabilityAssignmentRecord | None: ...

    def create_mapping(
        self,
        requirement_id: str,
        product_version_id: str,
        capability_id: str,
        rationale: str,
        confidence: float,
    ) -> MappingRecord: ...

    def get_mapping(self, mapping_id: str) -> MappingRecord | None: ...

    def attach_product_document(
        self, product_version_id: str, document_version_id: str, source_type: str
    ) -> dict[str, Any]: ...

    def product_document_exists(
        self, product_version_id: str, document_version_id: str, source_type: str
    ) -> bool: ...

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
    ) -> tuple[EvidenceRecord, EvidenceSpanRecord]: ...

    def get_evidence_span(self, span_id: str) -> EvidenceSpanRecord | None: ...

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None: ...

    def count_open_conflicts(self, requirement_id: str) -> int: ...

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
    ) -> DecisionRecord: ...

    def get_decision(self, decision_id: str) -> DecisionRecord | None: ...

    def list_decision_evidence(self, decision_id: str) -> list[DecisionEvidenceRecord]: ...

    def list_decision_span_ids(self, decision_id: str) -> list[str]: ...

    def update_draft_decision(
        self, decision_id: str, rationale: str | None, confidence: float | None
    ) -> DecisionRecord: ...

    def approve_decision(
        self,
        decision_id: str,
        approved_at: datetime,
        reviewer_principal_id: str,
        comment: str,
        review_mode: str,
    ) -> DecisionRecord: ...

    def record_decision_review(
        self,
        decision_id: str,
        *,
        decision_status: str,
        review_status: str,
        reviewer_principal_id: str,
        comment: str,
        review_mode: str,
    ) -> DecisionRecord: ...

    def next_response_version(self, rfp_id: str) -> int: ...

    def get_snapshot_item(self, decision_id: str) -> SnapshotItemRecord: ...

    def create_response(
        self,
        *,
        response_id: str,
        rfp_id: str,
        version_no: int,
        assessment_as_of: date,
        snapshot_hash: str,
        snapshot_json: dict[str, Any],
    ) -> ResponseRecord: ...

    def get_response(self, response_id: str) -> ResponseRecord | None: ...

    def get_response_export(self, response_id: str) -> ExportRecord | None: ...

    def create_response_export(
        self,
        *,
        response_id: str,
        format: str,
        object_key: str,
        sha256: str,
        size_bytes: int,
    ) -> ExportRecord: ...

    def get_export(self, export_id: str) -> ExportRecord | None: ...


class UnitOfWork(Protocol):
    repo: Stage1Repository

    def __enter__(self) -> UnitOfWork: ...

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class UnitOfWorkFactory(Protocol):
    def __call__(self, workspace_id: str | None) -> UnitOfWork: ...
