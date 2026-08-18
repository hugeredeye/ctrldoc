from datetime import date

import pytest

from ctrl_v2.domain.enums import (
    ComplianceOutcome,
    DecisionStatus,
    EvidenceAuthorityLevel,
    ReviewRisk,
)
from ctrl_v2.domain.exceptions import InvariantViolation
from ctrl_v2.domain.models import (
    DecisionApprovalCandidate,
    EvidenceBasis,
    ReviewSignals,
    TemporalScope,
)
from ctrl_v2.domain.policies import classify_review_risk, validate_decision_approval


def test_strong_unambiguous_evidence_is_low_risk():
    risk = classify_review_risk(
        ReviewSignals(
            confidence=0.95,
            authority_level=EvidenceAuthorityLevel.AUTHORITATIVE,
        )
    )
    assert risk is ReviewRisk.LOW


def test_conflict_is_blocking_even_with_high_confidence():
    risk = classify_review_risk(
        ReviewSignals(
            confidence=0.99,
            authority_level=EvidenceAuthorityLevel.AUTHORITATIVE,
            has_conflict=True,
        )
    )
    assert risk is ReviewRisk.BLOCKING


def test_temporally_expired_evidence_cannot_support_comply_approval():
    candidate = DecisionApprovalCandidate(
        decision_id="decision",
        workspace_id="workspace",
        outcome=ComplianceOutcome.COMPLY,
        status=DecisionStatus.DRAFT,
        assessment_as_of=date(2026, 8, 17),
        evidence=(
            EvidenceBasis(
                evidence_span_id="span",
                document_version_id="version",
                authority_level=EvidenceAuthorityLevel.AUTHORITATIVE,
                temporal_scope=TemporalScope(date(2024, 1, 1), date(2025, 12, 31)),
            ),
        ),
    )
    with pytest.raises(InvariantViolation, match="temporally applicable"):
        validate_decision_approval(candidate)
