from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Literal

from .authoring import dataset_sha256
from .error_analysis import ErrorAnalysisReport, analyze_error_slices
from .experiment import (
    ExperimentModel,
    RetrievalExperimentSuite,
    RetrievalProblem,
    build_retrieval_problem,
    run_retrieval_experiment,
)
from .gold_dataset import GoldDataset
from .neural_models import (
    CrossEncoderBackend,
    CrossEncoderReranker,
    E5EmbeddingModel,
    SentenceEmbeddingBackend,
)
from .retrieval import BM25Retriever, DenseRetriever, HybridRetriever, IdentityReranker
from .retrieval_contracts import JsonScalar, RetrievalQuery, RetrievedEvidenceSpan
from .semantic_config import SemanticExperimentConfig


class SemanticExperimentResult(ExperimentModel):
    schema_version: Literal["1.0"] = "1.0"
    configuration: SemanticExperimentConfig
    suite: RetrievalExperimentSuite
    error_analysis: ErrorAnalysisReport


class PrecomputedRetriever:
    method = "hybrid"
    implementation_id = "materialized-weighted-rrf-v1"

    def __init__(
        self,
        problem: RetrievalProblem,
        rankings: Mapping[str, tuple[RetrievedEvidenceSpan, ...]],
        *,
        embedding_model_id: str,
        parameters: Mapping[str, JsonScalar],
    ) -> None:
        self._candidate_count = len(problem.corpus)
        self._rankings = dict(rankings)
        self._embedding_model_id = embedding_model_id
        self._parameters = dict(parameters)

    @property
    def embedding_model_id(self) -> str:
        return self._embedding_model_id

    @property
    def parameters(self) -> Mapping[str, JsonScalar]:
        return self._parameters

    @property
    def candidate_count(self) -> int:
        return self._candidate_count

    def retrieve(self, query: RetrievalQuery, *, limit: int) -> tuple[RetrievedEvidenceSpan, ...]:
        if limit <= 0:
            raise ValueError("retrieval limit must be positive")
        try:
            ranked = self._rankings[query.query_id]
        except KeyError as exc:
            raise ValueError(f"No materialized retrieval for query {query.query_id}") from exc
        return tuple(
            candidate.model_copy(update={"rank": rank})
            for rank, candidate in enumerate(ranked[:limit], start=1)
        )


def _materialize_hybrid(
    problem: RetrievalProblem,
    hybrid: HybridRetriever,
    *,
    candidate_n: int,
    timer_ns: Callable[[], int],
) -> tuple[dict[str, tuple[RetrievedEvidenceSpan, ...]], dict[str, float]]:
    rankings: dict[str, tuple[RetrievedEvidenceSpan, ...]] = {}
    latencies: dict[str, float] = {}
    for judgment in problem.judgments:
        started = timer_ns()
        rankings[judgment.query.query_id] = hybrid.retrieve(judgment.query, limit=candidate_n)
        latencies[judgment.query.query_id] = max(timer_ns() - started, 0) / 1_000_000
    return rankings, latencies


def run_semantic_matrix(
    dataset: GoldDataset,
    configuration: SemanticExperimentConfig,
    *,
    code_version: str,
    embedding_backend: SentenceEmbeddingBackend | None = None,
    reranker_backend: CrossEncoderBackend | None = None,
    timer_ns: Callable[[], int] = time.perf_counter_ns,
) -> SemanticExperimentResult:
    digest = dataset_sha256(dataset)
    configuration.assert_no_test_leakage(digest)
    problem = build_retrieval_problem(dataset)
    lexical = BM25Retriever(problem.corpus)
    embedding = E5EmbeddingModel(configuration.embedding, backend=embedding_backend)
    reranker = CrossEncoderReranker(configuration.reranker, backend=reranker_backend)

    try:
        dense = DenseRetriever(problem.corpus, embedding)
        hybrid = HybridRetriever(lexical, dense, configuration.hybrid_config())
        identity = IdentityReranker()
        common = {
            "random_seed": configuration.random_seed,
            "code_version": code_version,
            "timer_ns": timer_ns,
        }
        bm25_run = run_retrieval_experiment(
            dataset,
            problem,
            lexical,
            identity,
            retrieval_limit=configuration.final_k,
            final_limit=configuration.final_k,
            method_label="bm25",
            **common,
        )
        dense_run = run_retrieval_experiment(
            dataset,
            problem,
            dense,
            identity,
            retrieval_limit=configuration.final_k,
            final_limit=configuration.final_k,
            method_label="neural_dense",
            **common,
        )
        hybrid_run = run_retrieval_experiment(
            dataset,
            problem,
            hybrid,
            identity,
            retrieval_limit=configuration.final_k,
            final_limit=configuration.final_k,
            method_label="hybrid",
            **common,
        )
        materialized, hybrid_latencies = _materialize_hybrid(
            problem,
            hybrid,
            candidate_n=configuration.candidate_n,
            timer_ns=timer_ns,
        )
        precomputed = PrecomputedRetriever(
            problem,
            materialized,
            embedding_model_id=dense.embedding_model_id,
            parameters={
                **dict(hybrid.parameters),
                "materialized_candidate_n": configuration.candidate_n,
            },
        )
        embedding.close()
        reranked_run = run_retrieval_experiment(
            dataset,
            problem,
            precomputed,
            reranker,
            retrieval_limit=configuration.candidate_n,
            final_limit=configuration.final_k,
            method_label="hybrid_cross_encoder",
            retrieval_latency_overrides_ms=hybrid_latencies,
            **common,
        )
    finally:
        embedding.close()
        reranker.close()

    runs = (bm25_run, dense_run, hybrid_run, reranked_run)
    suite = RetrievalExperimentSuite(
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.version,
        dataset_sha256=digest,
        runs=runs,
    )
    return SemanticExperimentResult(
        configuration=configuration,
        suite=suite,
        error_analysis=analyze_error_slices(
            problem,
            runs,
            cutoff=configuration.final_k,
        ),
    )
