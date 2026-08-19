from __future__ import annotations

import math
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


@dataclass(frozen=True, slots=True)
class RetrievalMetricCase:
    query_id: str
    positive_evidence_span_ids: frozenset[str]
    ranked_evidence_span_ids: tuple[str, ...]
    hard_negative_evidence_span_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.query_id:
            raise ValueError("query_id cannot be empty")
        if not self.positive_evidence_span_ids:
            raise ValueError("retrieval metric case requires at least one positive")
        overlap = self.positive_evidence_span_ids & self.hard_negative_evidence_span_ids
        if overlap:
            raise ValueError(f"evidence cannot be positive and hard-negative: {sorted(overlap)}")
        if len(self.ranked_evidence_span_ids) != len(set(self.ranked_evidence_span_ids)):
            raise ValueError("ranked evidence span IDs must be unique")


@dataclass(frozen=True, slots=True)
class RetrievalMetrics:
    query_count: int
    evidence_recall_at_1: float
    evidence_recall_at_3: float
    evidence_recall_at_5: float
    mrr: float
    ndcg_at_1: float
    ndcg_at_3: float
    ndcg_at_5: float

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _recall_at_k(case: RetrievalMetricCase, k: int) -> float:
    found = case.positive_evidence_span_ids & set(case.ranked_evidence_span_ids[:k])
    return len(found) / len(case.positive_evidence_span_ids)


def _reciprocal_rank(case: RetrievalMetricCase) -> float:
    for rank, evidence_span_id in enumerate(case.ranked_evidence_span_ids, start=1):
        if evidence_span_id in case.positive_evidence_span_ids:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(case: RetrievalMetricCase, k: int) -> float:
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, evidence_span_id in enumerate(case.ranked_evidence_span_ids[:k], start=1)
        if evidence_span_id in case.positive_evidence_span_ids
    )
    ideal_hits = min(len(case.positive_evidence_span_ids), k)
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0


def evaluate_retrieval(cases: list[RetrievalMetricCase]) -> RetrievalMetrics:
    if not cases:
        return RetrievalMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    def mean(values: list[float]) -> float:
        return sum(values) / len(values)

    return RetrievalMetrics(
        query_count=len(cases),
        evidence_recall_at_1=mean([_recall_at_k(case, 1) for case in cases]),
        evidence_recall_at_3=mean([_recall_at_k(case, 3) for case in cases]),
        evidence_recall_at_5=mean([_recall_at_k(case, 5) for case in cases]),
        mrr=mean([_reciprocal_rank(case) for case in cases]),
        ndcg_at_1=mean([_ndcg_at_k(case, 1) for case in cases]),
        ndcg_at_3=mean([_ndcg_at_k(case, 3) for case in cases]),
        ndcg_at_5=mean([_ndcg_at_k(case, 5) for case in cases]),
    )


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
