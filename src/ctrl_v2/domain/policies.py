from __future__ import annotations

from .enums import (
    ComplianceOutcome,
    DecisionStatus,
    EvidenceAuthorityLevel,
    ReviewRisk,
)
from .exceptions import InvariantViolation
from .models import DecisionApprovalCandidate, ReviewSignals

_AUTHORITY_RANK = {
    EvidenceAuthorityLevel.UNVERIFIED: 0,
    EvidenceAuthorityLevel.WEAK: 1,
    EvidenceAuthorityLevel.SUPPORTING: 2,
    EvidenceAuthorityLevel.STRONG: 3,
    EvidenceAuthorityLevel.AUTHORITATIVE: 4,
}


def classify_review_risk(signals: ReviewSignals) -> ReviewRisk:
    if signals.has_conflict or signals.policy_required:
        return ReviewRisk.BLOCKING
    if signals.ambiguous or signals.confidence < 0.60:
        return ReviewRisk.HIGH
    authority_rank = _AUTHORITY_RANK.get(signals.authority_level, 0)
    if signals.confidence < 0.80 or authority_rank < 2:
        return ReviewRisk.MEDIUM
    return ReviewRisk.LOW


def intermediate_human_intervention_required(risk: ReviewRisk) -> bool:
    return risk in {ReviewRisk.HIGH, ReviewRisk.BLOCKING}


def validate_decision_approval(candidate: DecisionApprovalCandidate) -> None:
    if candidate.status is DecisionStatus.APPROVED:
        raise InvariantViolation("An approved decision is immutable")
    if candidate.outcome in {ComplianceOutcome.COMPLY, ComplianceOutcome.PARTIAL}:
        if not candidate.evidence:
            raise InvariantViolation(
                "APPROVED COMPLY and PARTIAL decisions require an EvidenceSpan"
            )
        has_temporally_valid_evidence = any(
            item.temporal_scope.contains(candidate.assessment_as_of) for item in candidate.evidence
        )
        if not has_temporally_valid_evidence:
            raise InvariantViolation(
                "No EvidenceSpan is temporally applicable to the decision assessment date"
            )
