from __future__ import annotations

from dataclasses import asdict, dataclass

from ctrl_v2.domain.enums import ComplianceOutcome

from .contracts import EvaluationFixture


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    atomic_requirement_recall: float
    evidence_recall_at_k: float
    compliance_accuracy: float
    critical_false_comply_rate: float
    unedited_human_approval_rate: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def evaluate(fixture: EvaluationFixture) -> EvaluationMetrics:
    expected_requirements = sum(len(case.expected_requirement_keys) for case in fixture.extraction)
    recalled_requirements = sum(
        len(case.expected_requirement_keys & case.predicted_requirement_keys)
        for case in fixture.extraction
    )

    retrieval_recalls = []
    for case in fixture.retrieval:
        expected = case.expected_evidence_span_ids
        found = expected & set(case.ranked_evidence_span_ids[: case.k])
        retrieval_recalls.append(_ratio(len(found), len(expected)))

    correct_decisions = sum(case.expected == case.predicted for case in fixture.decisions)
    approved_unedited = sum(case.human_approved_without_edit for case in fixture.decisions)

    critical_non_comply = [
        case for case in fixture.conflicts if case.is_critical and case.expected_conflict
    ]
    false_comply = sum(
        case.decision in {ComplianceOutcome.COMPLY, ComplianceOutcome.PARTIAL}
        and not case.predicted_conflict
        for case in critical_non_comply
    )

    return EvaluationMetrics(
        atomic_requirement_recall=_ratio(recalled_requirements, expected_requirements),
        evidence_recall_at_k=(
            sum(retrieval_recalls) / len(retrieval_recalls) if retrieval_recalls else 0.0
        ),
        compliance_accuracy=_ratio(correct_decisions, len(fixture.decisions)),
        critical_false_comply_rate=_ratio(false_comply, len(critical_non_comply)),
        unedited_human_approval_rate=_ratio(approved_unedited, len(fixture.decisions)),
    )
