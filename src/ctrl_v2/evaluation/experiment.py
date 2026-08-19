from __future__ import annotations

import hashlib
import json
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .authoring import dataset_sha256
from .gold_dataset import GoldDataset, GoldEvidenceSpan
from .metrics import RetrievalMetricCase, evaluate_retrieval
from .retrieval_contracts import (
    EvidenceReranker,
    EvidenceRetriever,
    EvidenceSpanCandidate,
    EvidenceSpanProvenance,
    JsonScalar,
    RetrievalQuery,
    RetrievedEvidenceSpan,
)


class ExperimentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RetrievalJudgment(ExperimentModel):
    query: RetrievalQuery
    positive_evidence_span_ids: frozenset[str] = Field(min_length=1)
    hard_negative_evidence_span_ids: frozenset[str] = frozenset()
    hard_negative_error_tags: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class RetrievalProblem(ExperimentModel):
    corpus: tuple[EvidenceSpanCandidate, ...] = Field(min_length=1)
    judgments: tuple[RetrievalJudgment, ...] = Field(min_length=1)


class RetrievalCaseResult(ExperimentModel):
    query_id: str
    latency_ms: float = Field(ge=0)
    retrieval_latency_ms: float = Field(ge=0)
    reranking_latency_ms: float = Field(ge=0)
    candidate_count: int = Field(ge=0)
    final_candidate_count: int = Field(ge=0)
    corpus_size: int = Field(ge=0)
    ranked_candidates: tuple[RetrievedEvidenceSpan, ...]


class RetrievalRunMetadata(ExperimentModel):
    schema_version: Literal["2.0"] = "2.0"
    run_id: str
    dataset_id: str
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    method_label: str
    retrieval_method: str
    retrieval_implementation: str
    embedding_model_id: str | None = None
    reranker_implementation: str
    reranker_model_id: str | None = None
    parameters: dict[str, JsonScalar]
    random_seed: int
    code_version: str
    candidate_limit: int = Field(gt=0)
    final_limit: int = Field(gt=0)


class RetrievalExperimentRun(ExperimentModel):
    metadata: RetrievalRunMetadata
    metrics: dict[str, float | int]
    mean_latency_ms: float = Field(ge=0)
    p50_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)
    total_latency_ms: float = Field(ge=0)
    cases: tuple[RetrievalCaseResult, ...]


class RetrievalExperimentSuite(ExperimentModel):
    schema_version: Literal["2.0"] = "2.0"
    dataset_id: str
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runs: tuple[RetrievalExperimentRun, ...]


def _canonical_span_id(span: GoldEvidenceSpan) -> str:
    if span.key is not None:
        return span.key
    payload = json.dumps(
        {
            "asset_path": span.asset_path,
            "authority_level": span.authority_level,
            "document_key": span.document_key,
            "document_version": span.document_version,
            "exact_quote": span.exact_quote,
            "locator": span.locator.model_dump(mode="json"),
            "product_version_key": span.product_version_key,
            "source_sha256": span.source_sha256,
            "source_type": span.source_type,
            "valid_from": span.valid_from.isoformat(),
            "valid_to": span.valid_to.isoformat() if span.valid_to else None,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"canonical-text:{hashlib.sha256(payload).hexdigest()}"


def _candidate_from_gold(span: GoldEvidenceSpan) -> EvidenceSpanCandidate:
    return EvidenceSpanCandidate(
        evidence_span_id=_canonical_span_id(span),
        canonical_text=span.exact_quote,
        provenance=EvidenceSpanProvenance(
            asset_path=span.asset_path,
            document_key=span.document_key,
            document_version=span.document_version,
            source_sha256=span.source_sha256,
            locator=span.locator,
            source_type=span.source_type,
            authority_level=span.authority_level,
            valid_from=span.valid_from,
            valid_to=span.valid_to,
            product_version_key=span.product_version_key,
        ),
    )


def build_retrieval_problem(dataset: GoldDataset) -> RetrievalProblem:
    corpus_by_id: dict[str, EvidenceSpanCandidate] = {}
    judgments: list[RetrievalJudgment] = []
    for case in dataset.cases:
        case_spans = (*case.gold_evidence_spans, *case.hard_negative_evidence)
        for span in case_spans:
            candidate = _candidate_from_gold(span)
            existing = corpus_by_id.setdefault(candidate.evidence_span_id, candidate)
            if existing != candidate:
                raise ValueError(
                    "evidence span ID has conflicting canonical content: "
                    f"{candidate.evidence_span_id}"
                )
        for atomic in case.gold_atomic_requirements:
            positives = frozenset(
                _canonical_span_id(span)
                for span in case.gold_evidence_spans
                if span.atomic_requirement_key == atomic.key
            )
            if not positives:
                raise ValueError(
                    f"retrieval gold positives are missing for {case.case_id}:{atomic.key}"
                )
            hard_negatives = frozenset(
                _canonical_span_id(span)
                for span in case.hard_negative_evidence
                if span.atomic_requirement_key == atomic.key
            )
            hard_negative_error_tags = {
                _canonical_span_id(span): tuple(tag.value for tag in span.error_tags)
                for span in case.hard_negative_evidence
                if span.atomic_requirement_key == atomic.key
            }
            judgments.append(
                RetrievalJudgment(
                    query=RetrievalQuery(
                        query_id=f"{case.case_id}:{atomic.key}",
                        case_id=case.case_id,
                        atomic_requirement_key=atomic.key,
                        requirement_text=atomic.atomic_text,
                        source_context=case.source_requirement.context,
                    ),
                    positive_evidence_span_ids=positives,
                    hard_negative_evidence_span_ids=hard_negatives,
                    hard_negative_error_tags=hard_negative_error_tags,
                )
            )
    return RetrievalProblem(
        corpus=tuple(sorted(corpus_by_id.values(), key=lambda item: item.evidence_span_id)),
        judgments=tuple(sorted(judgments, key=lambda item: item.query.query_id)),
    )


def _run_id(metadata: Mapping[str, object]) -> str:
    payload = json.dumps(
        metadata,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def resolve_git_commit(repository: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return result.stdout.strip() or "unknown"


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def run_retrieval_experiment(
    dataset: GoldDataset,
    problem: RetrievalProblem,
    retriever: EvidenceRetriever,
    reranker: EvidenceReranker,
    *,
    retrieval_limit: int = 5,
    final_limit: int | None = None,
    method_label: str | None = None,
    random_seed: int = 0,
    code_version: str = "unknown",
    timer_ns: Callable[[], int] = time.perf_counter_ns,
    retrieval_latency_overrides_ms: Mapping[str, float] | None = None,
) -> RetrievalExperimentRun:
    if retrieval_limit <= 0:
        raise ValueError("retrieval_limit must be positive")
    resolved_final_limit = final_limit if final_limit is not None else retrieval_limit
    if resolved_final_limit <= 0 or resolved_final_limit > retrieval_limit:
        raise ValueError("final_limit must be positive and cannot exceed retrieval_limit")
    dataset_digest = dataset_sha256(dataset)
    parameters = {
        **dict(retriever.parameters),
        **{f"reranker.{key}": value for key, value in reranker.parameters.items()},
    }
    fingerprint_payload: dict[str, object] = {
        "dataset_id": dataset.dataset_id,
        "dataset_version": dataset.version,
        "dataset_sha256": dataset_digest,
        "method_label": method_label or retriever.method,
        "retrieval_method": retriever.method,
        "retrieval_implementation": retriever.implementation_id,
        "embedding_model_id": retriever.embedding_model_id,
        "reranker_implementation": reranker.implementation_id,
        "reranker_model_id": reranker.model_id,
        "parameters": parameters,
        "random_seed": random_seed,
        "code_version": code_version,
        "candidate_limit": retrieval_limit,
        "final_limit": resolved_final_limit,
    }
    metadata = RetrievalRunMetadata(
        run_id=_run_id(fingerprint_payload),
        **fingerprint_payload,
    )
    case_results: list[RetrievalCaseResult] = []
    metric_cases: list[RetrievalMetricCase] = []
    for judgment in problem.judgments:
        started = timer_ns()
        retrieved = retriever.retrieve(judgment.query, limit=retrieval_limit)
        retrieved_at = timer_ns()
        ranked = reranker.rerank(judgment.query, retrieved, limit=resolved_final_limit)
        completed_at = timer_ns()
        measured_retrieval_ms = max(retrieved_at - started, 0) / 1_000_000
        retrieval_ms = (
            retrieval_latency_overrides_ms[judgment.query.query_id]
            if retrieval_latency_overrides_ms
            and judgment.query.query_id in retrieval_latency_overrides_ms
            else measured_retrieval_ms
        )
        reranking_ms = max(completed_at - retrieved_at, 0) / 1_000_000
        elapsed_ms = retrieval_ms + reranking_ms
        ranked_ids = tuple(item.candidate.evidence_span_id for item in ranked)
        case_results.append(
            RetrievalCaseResult(
                query_id=judgment.query.query_id,
                latency_ms=elapsed_ms,
                retrieval_latency_ms=retrieval_ms,
                reranking_latency_ms=reranking_ms,
                candidate_count=len(retrieved),
                final_candidate_count=len(ranked),
                corpus_size=retriever.candidate_count,
                ranked_candidates=ranked,
            )
        )
        metric_cases.append(
            RetrievalMetricCase(
                query_id=judgment.query.query_id,
                positive_evidence_span_ids=judgment.positive_evidence_span_ids,
                hard_negative_evidence_span_ids=judgment.hard_negative_evidence_span_ids,
                ranked_evidence_span_ids=ranked_ids,
            )
        )
    total_latency = sum(item.latency_ms for item in case_results)
    latencies = [item.latency_ms for item in case_results]
    return RetrievalExperimentRun(
        metadata=metadata,
        metrics=evaluate_retrieval(metric_cases).as_dict(),
        mean_latency_ms=total_latency / len(case_results) if case_results else 0.0,
        p50_latency_ms=_percentile(latencies, 0.50),
        p95_latency_ms=_percentile(latencies, 0.95),
        total_latency_ms=total_latency,
        cases=tuple(case_results),
    )


def run_retrieval_comparison(
    dataset: GoldDataset,
    retrievers: Sequence[EvidenceRetriever],
    reranker: EvidenceReranker,
    *,
    retrieval_limit: int = 5,
    random_seed: int = 0,
    code_version: str = "unknown",
    timer_ns: Callable[[], int] = time.perf_counter_ns,
) -> RetrievalExperimentSuite:
    problem = build_retrieval_problem(dataset)
    if any(retriever.candidate_count != len(problem.corpus) for retriever in retrievers):
        raise ValueError("all retrievers must use the dataset retrieval corpus")
    runs = tuple(
        run_retrieval_experiment(
            dataset,
            problem,
            retriever,
            reranker,
            retrieval_limit=retrieval_limit,
            final_limit=retrieval_limit,
            method_label=retriever.method,
            random_seed=random_seed,
            code_version=code_version,
            timer_ns=timer_ns,
        )
        for retriever in retrievers
    )
    return RetrievalExperimentSuite(
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.version,
        dataset_sha256=dataset_sha256(dataset),
        runs=runs,
    )
