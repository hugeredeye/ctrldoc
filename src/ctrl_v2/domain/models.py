from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from .enums import (
    ComplianceOutcome,
    DecisionStatus,
    EvidenceAuthorityLevel,
    ReviewRisk,
)


@dataclass(frozen=True, slots=True)
class TemporalScope:
    valid_from: date | None = None
    valid_to: date | None = None

    def contains(self, value: date) -> bool:
        return (self.valid_from is None or self.valid_from <= value) and (
            self.valid_to is None or value <= self.valid_to
        )


@dataclass(frozen=True, slots=True)
class EvidenceBasis:
    evidence_span_id: str
    document_version_id: str
    authority_level: EvidenceAuthorityLevel
    temporal_scope: TemporalScope


@dataclass(frozen=True, slots=True)
class DecisionApprovalCandidate:
    decision_id: str
    workspace_id: str
    outcome: ComplianceOutcome
    status: DecisionStatus
    assessment_as_of: date
    evidence: tuple[EvidenceBasis, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ReviewSignals:
    confidence: float
    authority_level: EvidenceAuthorityLevel | None
    ambiguous: bool = False
    has_conflict: bool = False
    policy_required: bool = False


@dataclass(frozen=True, slots=True)
class ResponseSnapshotItem:
    requirement_id: str
    source_order: int
    requirement_text: str
    product_version_id: str
    product_name: str
    product_version: str
    capability_name: str
    decision_id: str
    outcome: ComplianceOutcome
    rationale: str
    risk: ReviewRisk
    evidence: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class ResponseSnapshot:
    response_id: str
    workspace_id: str
    rfp_id: str
    version: int
    assessment_as_of: date
    created_at: datetime
    items: tuple[ResponseSnapshotItem, ...]
