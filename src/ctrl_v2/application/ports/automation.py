from __future__ import annotations

from typing import Protocol

from ctrl_v2.application.structured_contracts import (
    AtomicRequirementExtractionBatch,
    CapabilityProposalBatch,
    ComplianceAssessmentDraft,
    ConflictDetectionBatch,
    EvidenceCandidateBatch,
    RequirementMappingProposalBatch,
)


class StructuredLlmGateway(Protocol):
    """Provider-neutral port. No Stage 1 implementation is provided."""

    def extract_requirements(self, input_ref: str) -> AtomicRequirementExtractionBatch: ...

    def assess_compliance(self, input_ref: str) -> ComplianceAssessmentDraft: ...

    def detect_conflicts(self, input_ref: str) -> ConflictDetectionBatch: ...


class RequirementMapper(Protocol):
    def propose(self, requirement_id: str) -> RequirementMappingProposalBatch: ...


class CapabilityBootstrapper(Protocol):
    """Future product-knowledge bootstrap. Suggestions always require human approval."""

    def propose(self, document_version_id: str) -> CapabilityProposalBatch: ...


class EvidenceRetriever(Protocol):
    """Every call is scoped to one workspace and one requirement."""

    def retrieve(
        self,
        *,
        workspace_id: str,
        requirement_id: str,
        product_version_id: str,
        limit: int,
    ) -> EvidenceCandidateBatch: ...
