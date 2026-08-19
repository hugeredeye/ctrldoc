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


class RetrievalProblem(ExperimentModel):
    corpus: tuple[EvidenceSpanCandidate, ...] = Field(min_length=1)
    judgments: tuple[RetrievalJudgment, ...] = Field(min_length=1)


class RetrievalCaseResult(ExperimentModel):
    query_id: str
    latency_ms: float = Field(ge=0)
    candidate_count: int = Field(ge=0)
    corpus_size: int = Field(ge=0)
    ranked_candidates: tuple[RetrievedEvidenceSpan, ...]


class RetrievalRunMetadata(ExperimentModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    dataset_id: str
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieval_method: str
    retrieval_implementation: str
    embedding_model_id: str | None = None
    reranker_implementation: str
    parameters: dict[str, JsonScalar]
    random_seed: int
    code_version: str
    retrieval_limit: int = Field(gt=0)


class RetrievalExperimentRun(ExperimentModel):
    metadata: RetrievalRunMetadata
    metrics: dict[str, float | int]
    mean_latency_ms: float = Field(ge=0)
    total_latency_ms: float = Field(ge=0)
    cases: tuple[RetrievalCaseResult, ...]


class RetrievalExperimentSuite(ExperimentModel):
    schema_version: Literal["1.0"] = "1.0"
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


def run_retrieval_experiment(
    dataset: GoldDataset,
    problem: RetrievalProblem,
    retriever: EvidenceRetriever,
    reranker: EvidenceReranker,
    *,
    retrieval_limit: int = 5,
    random_seed: int = 0,
    code_version: str = "unknown",
    timer_ns: Callable[[], int] = time.perf_counter_ns,
) -> RetrievalExperimentRun:
    if retrieval_limit <= 0:
        raise ValueError("retrieval_limit must be positive")
    dataset_digest = dataset_sha256(dataset)
    parameters = dict(retriever.parameters)
    fingerprint_payload: dict[str, object] = {
        "dataset_id": dataset.dataset_id,
        "dataset_version": dataset.version,
        "dataset_sha256": dataset_digest,
        "retrieval_method": retriever.method,
        "retrieval_implementation": retriever.implementation_id,
        "embedding_model_id": retriever.embedding_model_id,
        "reranker_implementation": reranker.implementation_id,
        "parameters": parameters,
        "random_seed": random_seed,
        "code_version": code_version,
        "retrieval_limit": retrieval_limit,
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
        ranked = reranker.rerank(judgment.query, retrieved, limit=retrieval_limit)
        elapsed_ms = max(timer_ns() - started, 0) / 1_000_000
        ranked_ids = tuple(item.candidate.evidence_span_id for item in ranked)
        case_results.append(
            RetrievalCaseResult(
                query_id=judgment.query.query_id,
                latency_ms=elapsed_ms,
                candidate_count=len(ranked),
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
    return RetrievalExperimentRun(
        metadata=metadata,
        metrics=evaluate_retrieval(metric_cases).as_dict(),
        mean_latency_ms=total_latency / len(case_results) if case_results else 0.0,
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
