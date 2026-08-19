from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from io import BytesIO
from pathlib import PurePath
from typing import Any, TypeVar
from uuid import uuid4

from ctrl_v2.application.ports.exporting import ResponseExporter
from ctrl_v2.application.ports.object_storage import ObjectStorage
from ctrl_v2.application.ports.parsing import DocumentParser
from ctrl_v2.application.ports.unit_of_work import Stage1Repository, UnitOfWorkFactory
from ctrl_v2.application.records import (
    BlockInsert,
    DecisionRecord,
    ExportRecord,
    SnapshotItemRecord,
)
from ctrl_v2.domain.enums import (
    ComplianceOutcome,
    DecisionStatus,
    EvidenceAuthorityLevel,
    ReviewMode,
    ReviewRisk,
    ReviewStatus,
)
from ctrl_v2.domain.exceptions import ConflictError, NotFoundError
from ctrl_v2.domain.models import (
    DecisionApprovalCandidate,
    EvidenceBasis,
    ReviewSignals,
    TemporalScope,
)
from ctrl_v2.domain.policies import classify_review_risk, validate_decision_approval

RecordT = TypeVar("RecordT")


def _new_id() -> str:
    return str(uuid4())


def _hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _required(value: RecordT | None, entity_name: str) -> RecordT:
    if value is None:
        raise NotFoundError(f"{entity_name} was not found")
    return value


class Stage1Workflow:
    """Application service owning transaction boundaries and domain-policy execution."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        storage: ObjectStorage,
        parser: DocumentParser,
        exporter: ResponseExporter,
        *,
        max_upload_bytes: int,
    ) -> None:
        self.uow_factory = uow_factory
        self.storage = storage
        self.parser = parser
        self.exporter = exporter
        self.max_upload_bytes = max_upload_bytes

    @staticmethod
    def _date_in_scope(value: date, valid_from: date | None, valid_to: date | None) -> bool:
        return (valid_from is None or valid_from <= value) and (
            valid_to is None or value <= valid_to
        )

    def create_workspace(self, name: str, initial_admin_principal_id: str) -> dict[str, Any]:
        workspace_id = _new_id()
        with self.uow_factory(workspace_id) as uow:
            workspace = uow.repo.create_workspace(
                workspace_id,
                name,
                initial_admin_principal_id,
            )
            uow.commit()
        return {"id": workspace.id, "name": workspace.name}

    def upload_document(
        self,
        *,
        workspace_id: str,
        title: str,
        kind: str,
        filename: str,
        media_type: str,
        content: bytes,
        published_at: date | None,
    ) -> dict[str, Any]:
        if not content:
            raise ConflictError("An empty document is not accepted")
        if len(content) > self.max_upload_bytes:
            raise ConflictError("The upload exceeds the configured size limit")
        if kind == "PRODUCT_KNOWLEDGE" and published_at is None:
            raise ConflictError("Product knowledge requires a publication date")
        parsed_blocks = self.parser.parse(filename, media_type, content)
        if not parsed_blocks:
            raise ConflictError("No textual content could be parsed from the document")

        document_id = _new_id()
        version_id = _new_id()
        representation_id = _new_id()
        digest = _hash(content)
        object_key = f"{workspace_id}/documents/{version_id}/{digest}"
        content_hash = _hash("\n".join(block.text for block in parsed_blocks).encode("utf-8"))
        blocks = tuple(
            BlockInsert(
                id=_new_id(),
                ordinal=block.ordinal,
                block_type=block.block_type,
                text=block.text,
                page_no=block.page_no,
                section_path=list(block.section_path),
                format_locator=block.locator,
                text_hash=block.text_hash,
            )
            for block in parsed_blocks
        )
        safe_filename = PurePath(filename.replace("\\", "/")).name
        with self.uow_factory(workspace_id) as uow:
            uploaded = uow.repo.create_document_bundle(
                document_id=document_id,
                version_id=version_id,
                representation_id=representation_id,
                title=title,
                kind=kind,
                original_filename=safe_filename,
                object_key=object_key,
                sha256=digest,
                media_type=media_type,
                size_bytes=len(content),
                published_at=published_at,
                parser_contract_version=self.parser.contract_version,
                parser_build=self.parser.parser_build,
                content_hash=content_hash,
                blocks=blocks,
            )
            self.storage.put(object_key, BytesIO(content))
            uow.commit()
        return {
            "document_id": uploaded.document_id,
            "document_version_id": uploaded.version_id,
            "representation_id": uploaded.representation_id,
            "sha256": digest,
            "size_bytes": len(content),
            "blocks": [self._block_dict(block) for block in uploaded.blocks],
        }

    @staticmethod
    def _block_dict(block: Any) -> dict[str, Any]:
        return {
            "id": block.id,
            "ordinal": block.ordinal,
            "block_type": block.block_type,
            "text": block.text,
            "page_no": block.page_no,
            "section_path": block.section_path,
            "locator": block.format_locator,
        }

    def get_document_content(self, workspace_id: str, version_id: str) -> tuple[bytes, str]:
        with self.uow_factory(workspace_id) as uow:
            version = _required(uow.repo.get_document_version(version_id), "DocumentVersion")
        return self.storage.get(version.object_key), version.media_type

    def create_rfp(
        self,
        workspace_id: str,
        name: str,
        source_document_version_id: str,
        assessment_as_of: date,
    ) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            _required(uow.repo.get_document_version(source_document_version_id), "DocumentVersion")
            rfp = uow.repo.create_rfp(name, source_document_version_id, assessment_as_of)
            uow.commit()
        return self._record_dict(
            workspace_id, rfp, "name", "source_document_version_id", "assessment_as_of", "status"
        )

    def create_requirement(
        self,
        *,
        workspace_id: str,
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
    ) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            rfp = _required(uow.repo.get_rfp(rfp_id), "Rfp")
            block = _required(uow.repo.get_block(document_block_id), "DocumentBlock")
            representation = _required(
                uow.repo.get_representation(block.representation_id), "DocumentRepresentation"
            )
            if representation.document_version_id != rfp.source_document_version_id:
                raise ConflictError("Requirement provenance must belong to the RFP DocumentVersion")
            if not 0 <= start_offset < end_offset <= len(block.text):
                raise ConflictError("Requirement source offsets are outside the parsed block")
            exact_quote = block.text[start_offset:end_offset]
            requirement = uow.repo.create_requirement(
                rfp_id=rfp_id,
                source_order=source_order,
                atomic_text=atomic_text,
                modality=modality,
                category=category,
                confidence=confidence,
                ambiguity_flags=ambiguity_flags,
                document_block_id=block.id,
                start_offset=start_offset,
                end_offset=end_offset,
                exact_quote=exact_quote,
                quote_hash=_hash(exact_quote.encode("utf-8")),
            )
            uow.commit()
        return self._record_dict(
            workspace_id,
            requirement,
            "rfp_id",
            "source_order",
            "atomic_text",
            "modality",
            "confidence",
            "ambiguity_flags",
            "status",
        )

    def create_product(self, workspace_id: str, name: str) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            product = uow.repo.create_product(name)
            uow.commit()
        return self._record_dict(workspace_id, product, "name", "status")

    def create_product_version(
        self,
        workspace_id: str,
        product_id: str,
        version_label: str,
        valid_from: date | None,
        valid_to: date | None,
    ) -> dict[str, Any]:
        if valid_from is None:
            raise ConflictError("ProductVersion requires a temporal valid_from boundary")
        if valid_to and valid_from > valid_to:
            raise ConflictError("ProductVersion valid_from must not be after valid_to")
        with self.uow_factory(workspace_id) as uow:
            _required(uow.repo.get_product(product_id), "Product")
            version = uow.repo.create_product_version(
                product_id, version_label, valid_from, valid_to
            )
            uow.commit()
        return self._record_dict(
            workspace_id,
            version,
            "product_id",
            "version_label",
            "valid_from",
            "valid_to",
            "status",
        )

    def create_capability(
        self, workspace_id: str, canonical_key: str, name: str, description: str
    ) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            capability = uow.repo.create_capability(canonical_key, name, description)
            uow.commit()
        return self._record_dict(
            workspace_id, capability, "canonical_key", "name", "description", "status"
        )

    def assign_capability(
        self,
        workspace_id: str,
        product_version_id: str,
        capability_id: str,
        valid_from: date | None,
        valid_to: date | None,
    ) -> dict[str, Any]:
        if valid_from is None:
            raise ConflictError("Capability assignment requires a temporal valid_from boundary")
        if valid_to and valid_from > valid_to:
            raise ConflictError("Capability validity range is invalid")
        with self.uow_factory(workspace_id) as uow:
            _required(uow.repo.get_product_version(product_version_id), "ProductVersion")
            _required(uow.repo.get_capability(capability_id), "Capability")
            assignment = uow.repo.create_capability_assignment(
                product_version_id, capability_id, valid_from, valid_to
            )
            uow.commit()
        return self._record_dict(
            workspace_id,
            assignment,
            "product_version_id",
            "capability_id",
            "valid_from",
            "valid_to",
            "approved",
        )

    def create_mapping(
        self,
        workspace_id: str,
        requirement_id: str,
        product_version_id: str,
        capability_id: str,
        rationale: str,
        confidence: float,
    ) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            _required(uow.repo.get_requirement(requirement_id), "Requirement")
            assignment = uow.repo.get_capability_assignment(product_version_id, capability_id)
            if assignment is None or not assignment.approved:
                raise ConflictError("Capability is not approved for this ProductVersion")
            mapping = uow.repo.create_mapping(
                requirement_id,
                product_version_id,
                capability_id,
                rationale,
                confidence,
            )
            uow.commit()
        return self._record_dict(
            workspace_id,
            mapping,
            "requirement_id",
            "product_version_id",
            "capability_id",
            "rationale",
            "confidence",
            "status",
        )

    def attach_product_document(
        self,
        workspace_id: str,
        product_version_id: str,
        document_version_id: str,
        source_type: str,
    ) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            _required(uow.repo.get_product_version(product_version_id), "ProductVersion")
            _required(uow.repo.get_document_version(document_version_id), "DocumentVersion")
            link = uow.repo.attach_product_document(
                product_version_id, document_version_id, source_type
            )
            uow.commit()
        return {"workspace_id": workspace_id, **link}

    def create_evidence_span(
        self,
        *,
        workspace_id: str,
        requirement_id: str,
        product_version_id: str,
        summary: str,
        source_type: str,
        authority_level: str,
        valid_from: date | None,
        valid_to: date | None,
        document_version_id: str,
        document_block_id: str,
        start_offset: int,
        end_offset: int,
    ) -> dict[str, Any]:
        if valid_from is None:
            raise ConflictError("Evidence requires a temporal valid_from boundary")
        if valid_to and valid_from > valid_to:
            raise ConflictError("Evidence validity range is invalid")
        with self.uow_factory(workspace_id) as uow:
            _required(uow.repo.get_requirement(requirement_id), "Requirement")
            _required(uow.repo.get_product_version(product_version_id), "ProductVersion")
            version = _required(
                uow.repo.get_document_version(document_version_id), "DocumentVersion"
            )
            if not uow.repo.product_document_exists(
                product_version_id, document_version_id, source_type
            ):
                raise ConflictError(
                    "Evidence source DocumentVersion is not registered for this ProductVersion"
                )
            block = _required(uow.repo.get_block(document_block_id), "DocumentBlock")
            representation = _required(
                uow.repo.get_representation(block.representation_id), "DocumentRepresentation"
            )
            if representation.document_version_id != version.id:
                raise ConflictError(
                    "EvidenceSpan block and representation must belong to the exact DocumentVersion"
                )
            if not 0 <= start_offset < end_offset <= len(block.text):
                raise ConflictError("EvidenceSpan offsets are outside the parsed block")
            exact_quote = block.text[start_offset:end_offset]
            evidence, span = uow.repo.create_evidence_span(
                requirement_id=requirement_id,
                product_version_id=product_version_id,
                summary=summary,
                source_type=source_type,
                authority_level=authority_level,
                valid_from=valid_from,
                valid_to=valid_to,
                document_version_id=version.id,
                representation_id=representation.id,
                document_block_id=block.id,
                start_offset=start_offset,
                end_offset=end_offset,
                exact_quote=exact_quote,
                quote_hash=_hash(exact_quote.encode("utf-8")),
                format_locator=block.format_locator,
            )
            uow.commit()
        return {
            "evidence_id": evidence.id,
            "evidence_span_id": span.id,
            "document_version_id": span.document_version_id,
            "exact_quote": span.exact_quote,
            "locator": span.format_locator,
            "authority_level": evidence.authority_level,
            "source_type": evidence.source_type,
            "valid_from": evidence.valid_from,
            "valid_to": evidence.valid_to,
        }

    def create_decision(
        self,
        *,
        workspace_id: str,
        mapping_id: str,
        outcome: ComplianceOutcome,
        rationale: str,
        confidence: float,
        evidence_span_ids: list[str],
        policy_required: bool,
    ) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            mapping = _required(uow.repo.get_mapping(mapping_id), "RequirementMapping")
            requirement = _required(uow.repo.get_requirement(mapping.requirement_id), "Requirement")
            rfp = _required(uow.repo.get_rfp(requirement.rfp_id), "Rfp")
            product_version = _required(
                uow.repo.get_product_version(mapping.product_version_id), "ProductVersion"
            )
            if not self._date_in_scope(
                rfp.assessment_as_of, product_version.valid_from, product_version.valid_to
            ):
                raise ConflictError("ProductVersion is not applicable on the RFP assessment date")
            assignment = uow.repo.get_capability_assignment(
                mapping.product_version_id, mapping.capability_id
            )
            if assignment is None or not self._date_in_scope(
                rfp.assessment_as_of, assignment.valid_from, assignment.valid_to
            ):
                raise ConflictError(
                    "Capability is not applicable to ProductVersion on the assessment date"
                )

            evidence_rows = []
            for span_id in dict.fromkeys(evidence_span_ids):
                span = _required(uow.repo.get_evidence_span(span_id), "EvidenceSpan")
                evidence = _required(uow.repo.get_evidence(span.evidence_id), "Evidence")
                if (
                    evidence.requirement_id != requirement.id
                    or evidence.product_version_id != mapping.product_version_id
                ):
                    raise ConflictError("EvidenceSpan is outside the decision requirement scope")
                evidence_rows.append(evidence)
            authority_rank = {
                EvidenceAuthorityLevel.UNVERIFIED: 0,
                EvidenceAuthorityLevel.WEAK: 1,
                EvidenceAuthorityLevel.SUPPORTING: 2,
                EvidenceAuthorityLevel.STRONG: 3,
                EvidenceAuthorityLevel.AUTHORITATIVE: 4,
            }
            strongest = max(
                (EvidenceAuthorityLevel(item.authority_level) for item in evidence_rows),
                key=authority_rank.__getitem__,
                default=None,
            )
            risk = classify_review_risk(
                ReviewSignals(
                    confidence=confidence,
                    authority_level=strongest,
                    ambiguous=bool(requirement.ambiguity_flags),
                    has_conflict=bool(uow.repo.count_open_conflicts(requirement.id)),
                    policy_required=policy_required,
                )
            )
            decision = uow.repo.create_decision(
                requirement_id=requirement.id,
                product_version_id=mapping.product_version_id,
                mapping_id=mapping.id,
                outcome=outcome.value,
                rationale=rationale,
                confidence=confidence,
                risk=risk.value,
                policy_required=policy_required,
                assessment_as_of=rfp.assessment_as_of,
                evidence_span_ids=list(dict.fromkeys(evidence_span_ids)),
            )
            uow.commit()
        return self._decision_dict(workspace_id, decision, evidence_span_ids)

    def update_decision(
        self,
        workspace_id: str,
        decision_id: str,
        *,
        rationale: str | None,
        confidence: float | None,
    ) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            decision = _required(uow.repo.get_decision(decision_id), "ComplianceDecision")
            if decision.status == DecisionStatus.APPROVED.value:
                raise ConflictError(
                    "An approved decision is immutable; create a superseding revision"
                )
            decision = uow.repo.update_draft_decision(decision_id, rationale, confidence)
            span_ids = uow.repo.list_decision_span_ids(decision_id)
            uow.commit()
        return self._decision_dict(workspace_id, decision, span_ids)

    def approve_decision(
        self,
        workspace_id: str,
        decision_id: str,
        reviewer_principal_id: str,
        comment: str,
        mode: ReviewMode = ReviewMode.SINGLE,
    ) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            decision = self._approve(
                uow.repo,
                decision_id,
                reviewer_principal_id,
                comment,
                mode,
            )
            span_ids = uow.repo.list_decision_span_ids(decision_id)
            uow.commit()
        return self._decision_dict(workspace_id, decision, span_ids)

    def batch_approve(
        self,
        workspace_id: str,
        decision_ids: list[str],
        reviewer_principal_id: str,
        comment: str,
    ) -> list[dict[str, Any]]:
        with self.uow_factory(workspace_id) as uow:
            approved = []
            for decision_id in dict.fromkeys(decision_ids):
                decision = _required(uow.repo.get_decision(decision_id), "ComplianceDecision")
                if decision.risk != ReviewRisk.LOW.value:
                    raise ConflictError("Only LOW-risk decisions are eligible for batch approval")
                approved.append(
                    self._approve(
                        uow.repo,
                        decision_id,
                        reviewer_principal_id,
                        comment,
                        ReviewMode.BATCH,
                    )
                )
            uow.commit()
        return [self._decision_dict(workspace_id, item, []) for item in approved]

    def reject_decision(
        self,
        workspace_id: str,
        decision_id: str,
        reviewer_principal_id: str,
        comment: str,
    ) -> dict[str, Any]:
        return self._record_review(
            workspace_id,
            decision_id,
            reviewer_principal_id,
            comment,
            decision_status=DecisionStatus.REJECTED,
            review_status=ReviewStatus.REJECTED,
        )

    def escalate_decision(
        self,
        workspace_id: str,
        decision_id: str,
        reviewer_principal_id: str,
        comment: str,
    ) -> dict[str, Any]:
        return self._record_review(
            workspace_id,
            decision_id,
            reviewer_principal_id,
            comment,
            decision_status=DecisionStatus.IN_REVIEW,
            review_status=ReviewStatus.ESCALATED,
        )

    def _record_review(
        self,
        workspace_id: str,
        decision_id: str,
        reviewer_principal_id: str,
        comment: str,
        *,
        decision_status: DecisionStatus,
        review_status: ReviewStatus,
    ) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            decision = _required(uow.repo.get_decision(decision_id), "ComplianceDecision")
            if decision.status == DecisionStatus.APPROVED.value:
                raise ConflictError("An approved decision is immutable")
            decision = uow.repo.record_decision_review(
                decision_id,
                decision_status=decision_status.value,
                review_status=review_status.value,
                reviewer_principal_id=reviewer_principal_id,
                comment=comment,
                review_mode=ReviewMode.SINGLE.value,
            )
            span_ids = uow.repo.list_decision_span_ids(decision_id)
            uow.commit()
        return self._decision_dict(workspace_id, decision, span_ids)

    @staticmethod
    def _approve(
        repo: Stage1Repository,
        decision_id: str,
        reviewer_principal_id: str,
        comment: str,
        mode: ReviewMode,
    ) -> DecisionRecord:
        decision = _required(repo.get_decision(decision_id), "ComplianceDecision")
        evidence_rows = repo.list_decision_evidence(decision_id)
        candidate = DecisionApprovalCandidate(
            decision_id=decision.id,
            workspace_id="scoped-by-uow",
            outcome=ComplianceOutcome(decision.outcome),
            status=DecisionStatus(decision.status),
            assessment_as_of=decision.assessment_as_of,
            evidence=tuple(
                EvidenceBasis(
                    evidence_span_id=row.span.id,
                    document_version_id=row.span.document_version_id,
                    authority_level=EvidenceAuthorityLevel(row.evidence.authority_level),
                    temporal_scope=TemporalScope(row.evidence.valid_from, row.evidence.valid_to),
                )
                for row in evidence_rows
            ),
        )
        validate_decision_approval(candidate)
        return repo.approve_decision(
            decision_id,
            approved_at=datetime.now(UTC),
            reviewer_principal_id=reviewer_principal_id,
            comment=comment,
            review_mode=mode.value,
        )

    def create_response(
        self, workspace_id: str, rfp_id: str, decision_ids: list[str]
    ) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            rfp = _required(uow.repo.get_rfp(rfp_id), "Rfp")
            requirements = uow.repo.list_accepted_requirements(rfp_id)
            decisions = [
                _required(uow.repo.get_decision(decision_id), "ComplianceDecision")
                for decision_id in dict.fromkeys(decision_ids)
            ]
            decision_by_requirement = {item.requirement_id: item for item in decisions}
            if len(decisions) != len(decision_by_requirement) or set(decision_by_requirement) != {
                item.id for item in requirements
            }:
                raise ConflictError(
                    "Response requires exactly one approved decision per requirement"
                )
            if any(item.status != DecisionStatus.APPROVED.value for item in decisions):
                raise ConflictError("Response can contain only approved decisions")

            response_id = _new_id()
            version_no = uow.repo.next_response_version(rfp_id)
            items = [
                self._snapshot_item(uow.repo.get_snapshot_item(decision_by_requirement[req.id].id))
                for req in requirements
            ]
            snapshot: dict[str, Any] = {
                "schema_version": "1.0",
                "response_id": response_id,
                "workspace_id": workspace_id,
                "rfp_id": rfp_id,
                "version_no": version_no,
                "assessment_as_of": rfp.assessment_as_of.isoformat(),
                "items": items,
            }
            snapshot_hash = _hash(_canonical_json(snapshot))
            snapshot["snapshot_hash"] = snapshot_hash
            response = uow.repo.create_response(
                response_id=response_id,
                rfp_id=rfp_id,
                version_no=version_no,
                assessment_as_of=rfp.assessment_as_of,
                snapshot_hash=snapshot_hash,
                snapshot_json=snapshot,
            )
            uow.commit()
        return {
            "id": response.id,
            "rfp_id": response.rfp_id,
            "version_no": response.version_no,
            "snapshot_hash": response.snapshot_hash,
            "items": items,
        }

    @staticmethod
    def _snapshot_item(item: SnapshotItemRecord) -> dict[str, Any]:
        decision = item.decision
        return {
            "requirement_id": item.requirement.id,
            "source_order": item.requirement.source_order,
            "requirement_text": item.requirement.atomic_text,
            "product_version_id": item.product_version.id,
            "product_name": item.product.name,
            "product_version": item.product_version.version_label,
            "capability_id": item.capability.id,
            "capability_name": item.capability.name,
            "decision_id": decision.id,
            "outcome": decision.outcome,
            "rationale": decision.rationale,
            "risk": decision.risk,
            "approved_by": decision.approved_by_principal_id,
            "approved_at": decision.approved_at.isoformat() if decision.approved_at else "",
            "evidence": [
                {
                    "evidence_span_id": evidence.evidence_span_id,
                    "source_type": evidence.source_type,
                    "authority_level": evidence.authority_level,
                    "document_version_id": evidence.document_version_id,
                    "document_sha256": evidence.document_sha256,
                    "locator": evidence.locator,
                    "locator_canonical": json.dumps(
                        evidence.locator,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "exact_quote": evidence.exact_quote,
                    "valid_from": evidence.valid_from.isoformat() if evidence.valid_from else "",
                    "valid_to": evidence.valid_to.isoformat() if evidence.valid_to else "",
                }
                for evidence in item.evidence
            ],
        }

    def export_response(self, workspace_id: str, response_id: str) -> dict[str, Any]:
        with self.uow_factory(workspace_id) as uow:
            response = _required(uow.repo.get_response(response_id), "Response")
            existing = uow.repo.get_response_export(response_id)
            if existing is not None:
                return self._export_dict(existing)
            payload = self.exporter.export(response.snapshot_json)
            digest = _hash(payload)
            object_key = (
                f"{workspace_id}/exports/{response.id}/{digest}.{self.exporter.format.lower()}"
            )
            self.storage.put(object_key, BytesIO(payload))
            export = uow.repo.create_response_export(
                response_id=response.id,
                format=self.exporter.format,
                object_key=object_key,
                sha256=digest,
                size_bytes=len(payload),
            )
            uow.commit()
        return self._export_dict(export)

    def get_export_content(self, workspace_id: str, export_id: str) -> bytes:
        with self.uow_factory(workspace_id) as uow:
            export = _required(uow.repo.get_export(export_id), "ResponseExport")
        return self.storage.get(export.object_key)

    @staticmethod
    def _record_dict(workspace_id: str, record: Any, *fields: str) -> dict[str, Any]:
        result = {"id": record.id, "workspace_id": workspace_id}
        result.update({field: getattr(record, field) for field in fields})
        return result

    @staticmethod
    def _decision_dict(
        workspace_id: str, decision: DecisionRecord, span_ids: Iterable[str]
    ) -> dict[str, Any]:
        return {
            "id": decision.id,
            "workspace_id": workspace_id,
            "mapping_id": decision.mapping_id,
            "requirement_id": decision.requirement_id,
            "product_version_id": decision.product_version_id,
            "outcome": decision.outcome,
            "rationale": decision.rationale,
            "confidence": decision.confidence,
            "risk": decision.risk,
            "assessment_as_of": decision.assessment_as_of,
            "status": decision.status,
            "approved_by_principal_id": decision.approved_by_principal_id,
            "evidence_span_ids": list(span_ids),
            "revision": decision.revision,
        }

    @staticmethod
    def _export_dict(export: ExportRecord) -> dict[str, Any]:
        return {
            "id": export.id,
            "response_id": export.response_id,
            "format": export.format,
            "sha256": export.sha256,
            "size_bytes": export.size_bytes,
        }
