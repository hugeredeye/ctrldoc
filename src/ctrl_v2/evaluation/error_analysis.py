from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from .experiment import ExperimentModel, RetrievalExperimentRun, RetrievalProblem


class ErrorSliceLabel(StrEnum):
    HARD_NEGATIVE_ABOVE_POSITIVE = "HARD_NEGATIVE_ABOVE_POSITIVE"
    WRONG_PRODUCT_VERSION = "WRONG_PRODUCT_VERSION"
    OBSOLETE_SOURCE = "OBSOLETE_SOURCE"
    ROADMAP_NOT_RELEASED = "ROADMAP_NOT_RELEASED"
    NON_ENTAILING = "NON_ENTAILING"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    TEMPORAL_VALIDITY = "TEMPORAL_VALIDITY"
    SOURCE_AUTHORITY = "SOURCE_AUTHORITY"
    LEXICAL_MISS_SEMANTIC_HIT = "LEXICAL_MISS_SEMANTIC_HIT"
    SEMANTIC_MISS_LEXICAL_HIT = "SEMANTIC_MISS_LEXICAL_HIT"


class ErrorSliceResult(ExperimentModel):
    label: ErrorSliceLabel
    eligible_query_count: int = Field(ge=0)
    error_query_count: int = Field(ge=0)
    query_ids: tuple[str, ...]


class MethodErrorAnalysis(ExperimentModel):
    method_label: str
    slices: tuple[ErrorSliceResult, ...]


class ErrorAnalysisReport(ExperimentModel):
    cutoff: int = Field(gt=0)
    methods: tuple[MethodErrorAnalysis, ...]
    cross_method_slices: tuple[ErrorSliceResult, ...]


_ANNOTATED_TAGS = tuple(
    label
    for label in ErrorSliceLabel
    if label
    not in {
        ErrorSliceLabel.HARD_NEGATIVE_ABOVE_POSITIVE,
        ErrorSliceLabel.LEXICAL_MISS_SEMANTIC_HIT,
        ErrorSliceLabel.SEMANTIC_MISS_LEXICAL_HIT,
    }
)


def _ranked_ids(run: RetrievalExperimentRun) -> dict[str, tuple[str, ...]]:
    return {
        case.query_id: tuple(
            candidate.candidate.evidence_span_id for candidate in case.ranked_candidates
        )
        for case in run.cases
    }


def _positive_hit(ids: tuple[str, ...], positives: frozenset[str], cutoff: int) -> bool:
    return bool(set(ids[:cutoff]) & positives)


def analyze_error_slices(
    problem: RetrievalProblem,
    runs: tuple[RetrievalExperimentRun, ...],
    *,
    cutoff: int,
) -> ErrorAnalysisReport:
    judgments = {item.query.query_id: item for item in problem.judgments}
    method_reports: list[MethodErrorAnalysis] = []
    rankings_by_method: dict[str, dict[str, tuple[str, ...]]] = {}

    for run in runs:
        label = run.metadata.method_label
        rankings = _ranked_ids(run)
        rankings_by_method[label] = rankings
        eligible_by_slice: dict[ErrorSliceLabel, set[str]] = {
            slice_label: set() for slice_label in _ANNOTATED_TAGS
        }
        errors_by_slice: dict[ErrorSliceLabel, set[str]] = {
            slice_label: set() for slice_label in _ANNOTATED_TAGS
        }
        hard_negative_eligible: set[str] = set()
        hard_negative_errors: set[str] = set()

        for query_id, judgment in judgments.items():
            ranked = rankings.get(query_id, ())[:cutoff]
            rank = {evidence_id: index for index, evidence_id in enumerate(ranked, start=1)}
            positive_ranks = [
                rank[evidence_id]
                for evidence_id in judgment.positive_evidence_span_ids
                if evidence_id in rank
            ]
            first_positive = min(positive_ranks, default=float("inf"))
            if judgment.hard_negative_evidence_span_ids:
                hard_negative_eligible.add(query_id)
            hard_negative_above = {
                evidence_id
                for evidence_id in judgment.hard_negative_evidence_span_ids
                if rank.get(evidence_id, float("inf")) < first_positive
            }
            if hard_negative_above:
                hard_negative_errors.add(query_id)

            for slice_label in _ANNOTATED_TAGS:
                tagged = {
                    evidence_id
                    for evidence_id, tags in judgment.hard_negative_error_tags.items()
                    if slice_label.value in tags
                }
                if not tagged:
                    continue
                eligible_by_slice[slice_label].add(query_id)
                if tagged & hard_negative_above:
                    errors_by_slice[slice_label].add(query_id)

        slices = [
            ErrorSliceResult(
                label=ErrorSliceLabel.HARD_NEGATIVE_ABOVE_POSITIVE,
                eligible_query_count=len(hard_negative_eligible),
                error_query_count=len(hard_negative_errors),
                query_ids=tuple(sorted(hard_negative_errors)),
            )
        ]
        slices.extend(
            ErrorSliceResult(
                label=slice_label,
                eligible_query_count=len(eligible_by_slice[slice_label]),
                error_query_count=len(errors_by_slice[slice_label]),
                query_ids=tuple(sorted(errors_by_slice[slice_label])),
            )
            for slice_label in _ANNOTATED_TAGS
        )
        method_reports.append(MethodErrorAnalysis(method_label=label, slices=tuple(slices)))

    lexical = rankings_by_method.get("bm25", {})
    semantic = rankings_by_method.get("neural_dense", {})
    lexical_miss: list[str] = []
    semantic_miss: list[str] = []
    comparable = sorted(set(lexical) & set(semantic))
    for query_id in comparable:
        positives = judgments[query_id].positive_evidence_span_ids
        lexical_hit = _positive_hit(lexical[query_id], positives, cutoff)
        semantic_hit = _positive_hit(semantic[query_id], positives, cutoff)
        if semantic_hit and not lexical_hit:
            lexical_miss.append(query_id)
        if lexical_hit and not semantic_hit:
            semantic_miss.append(query_id)

    return ErrorAnalysisReport(
        cutoff=cutoff,
        methods=tuple(method_reports),
        cross_method_slices=(
            ErrorSliceResult(
                label=ErrorSliceLabel.LEXICAL_MISS_SEMANTIC_HIT,
                eligible_query_count=len(comparable),
                error_query_count=len(lexical_miss),
                query_ids=tuple(lexical_miss),
            ),
            ErrorSliceResult(
                label=ErrorSliceLabel.SEMANTIC_MISS_LEXICAL_HIT,
                eligible_query_count=len(comparable),
                error_query_count=len(semantic_miss),
                query_ids=tuple(semantic_miss),
            ),
        ),
    )
