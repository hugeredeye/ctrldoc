from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from itertools import count
from pathlib import Path

import pytest

from ctrl_v2.evaluation.authoring import dataset_sha256, load_dataset
from ctrl_v2.evaluation.error_analysis import ErrorSliceLabel
from ctrl_v2.evaluation.experiment import build_retrieval_problem
from ctrl_v2.evaluation.neural_models import (
    CrossEncoderReranker,
    E5EmbeddingModel,
    NeuralModelError,
    NeuralModelLoadError,
)
from ctrl_v2.evaluation.retrieval import DenseRetriever
from ctrl_v2.evaluation.semantic_config import (
    RRFWeightSource,
    load_semantic_config,
)
from ctrl_v2.evaluation.semantic_experiment import run_semantic_matrix

FIXTURE = Path("evaluations/fixtures/stage2-retrieval-v1.json")
CONFIGURATION = Path("evaluations/config/semantic-retrieval-v1.json")


def _vector(index: int, dimension: int = 1024) -> tuple[float, ...]:
    values = [0.0] * dimension
    values[index] = 1.0
    return tuple(values)


class RecordingEmbeddingBackend:
    dimension = 1024

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], int, bool]] = []
        self.closed = False

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int,
        normalize: bool,
    ) -> Sequence[Sequence[float]]:
        self.calls.append((tuple(texts), batch_size, normalize))
        vectors = []
        for text in texts:
            lowered = text.casefold()
            if "not available" in lowered:
                vectors.append(_vector(3))
            elif "saml" in lowered:
                vectors.append(_vector(0))
            elif "aes-256" in lowered or "at rest" in lowered:
                vectors.append(_vector(1))
            elif "tls" in lowered or "in transit" in lowered:
                vectors.append(_vector(2))
            else:
                vectors.append(_vector(3))
        return vectors

    def close(self) -> None:
        self.closed = True


class RecordingCrossEncoderBackend:
    def __init__(self, *, prefer_hard_negatives: bool = False) -> None:
        self.pairs: list[tuple[str, str]] = []
        self.prefer_hard_negatives = prefer_hard_negatives
        self.closed = False

    def score(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        max_length: int,
    ) -> Sequence[float]:
        del batch_size, max_length
        self.pairs.extend(pairs)
        scores = []
        for _, document in pairs:
            is_hard_negative = "not available" in document or "in transit" in document
            preferred = is_hard_negative if self.prefer_hard_negatives else not is_hard_negative
            scores.append(5.0 if preferred else -5.0)
        return scores

    def close(self) -> None:
        self.closed = True


class NonFiniteEmbeddingBackend(RecordingEmbeddingBackend):
    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int,
        normalize: bool,
    ) -> Sequence[Sequence[float]]:
        del batch_size, normalize
        return tuple((math.nan, *([0.0] * 1023)) for _ in texts)


class NonFiniteCrossEncoderBackend(RecordingCrossEncoderBackend):
    def score(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        max_length: int,
    ) -> Sequence[float]:
        del batch_size, max_length
        return [math.nan] * len(pairs)


def _timer() -> Callable[[], int]:
    values = count(0, 1_000_000)
    return lambda: next(values)


def _test_configuration():
    configuration = load_semantic_config(CONFIGURATION)
    return configuration.model_copy(update={"candidate_n": 4, "final_k": 2})


def test_e5_applies_intended_asymmetric_preprocessing_and_normalization():
    configuration = _test_configuration()
    backend = RecordingEmbeddingBackend()
    model = E5EmbeddingModel(configuration.embedding, backend=backend)

    model.embed_queries(["  Платформа должна поддерживать SAML 2.0.  "])
    model.embed_documents(["  Exact SAML evidence.  "])

    query_call, document_call = backend.calls
    assert query_call[0] == (
        "Instruct: Given an RFI, RFP, or technical requirement, retrieve exact product "
        "evidence passages that prove or disprove the requirement\n"
        "Query: Платформа должна поддерживать SAML 2.0.",
    )
    assert document_call[0] == ("Exact SAML evidence.",)
    assert query_call[2] is True
    assert document_call[2] is True
    assert model.parameters["embedding_dimension"] == 1024
    assert model.parameters["model_revision"] == configuration.embedding.artifact.revision


def test_neural_dense_ranking_is_requirement_specific_and_nonfinite_fails_closed():
    dataset = load_dataset(FIXTURE, checked_in=True)
    problem = build_retrieval_problem(dataset)
    configuration = _test_configuration()
    dense = DenseRetriever(
        problem.corpus,
        E5EmbeddingModel(configuration.embedding, backend=RecordingEmbeddingBackend()),
    )

    tops = {
        judgment.query.query_id: dense.retrieve(judgment.query, limit=1)[
            0
        ].candidate.evidence_span_id
        for judgment in problem.judgments
    }
    assert tops == {
        "encryption-at-rest-001:REQ-AES-REST": "SPAN-AES-REST-V7",
        "saml-sso-001:REQ-SAML": "SPAN-SAML-V7",
    }

    with pytest.raises(ValueError, match="finite"):
        DenseRetriever(
            problem.corpus,
            E5EmbeddingModel(configuration.embedding, backend=NonFiniteEmbeddingBackend()),
        )


def test_missing_pinned_model_fails_without_feature_hashing_fallback(tmp_path):
    configuration = _test_configuration()
    missing = configuration.embedding.model_copy(update={"local_path": tmp_path / "missing"})
    model = E5EmbeddingModel(missing)

    with pytest.raises(NeuralModelLoadError, match="snapshot is incomplete"):
        model.embed_documents(["evidence"])


def test_semantic_matrix_records_models_scores_latency_and_provenance():
    dataset = load_dataset(FIXTURE, checked_in=True)
    configuration = _test_configuration()
    embedding_backend = RecordingEmbeddingBackend()
    reranker_backend = RecordingCrossEncoderBackend()

    result = run_semantic_matrix(
        dataset,
        configuration,
        code_version="test-commit",
        embedding_backend=embedding_backend,
        reranker_backend=reranker_backend,
        timer_ns=_timer(),
    )

    assert [run.metadata.method_label for run in result.suite.runs] == [
        "bm25",
        "neural_dense",
        "hybrid",
        "hybrid_cross_encoder",
    ]
    dense_run = result.suite.runs[1]
    hybrid_run = result.suite.runs[2]
    reranked_run = result.suite.runs[3]
    assert dense_run.metadata.embedding_model_id == (
        "intfloat/multilingual-e5-large-instruct@84344a23ee1820ac951bc365f1e91d094a911763"
    )
    assert reranked_run.metadata.reranker_model_id == (
        "BAAI/bge-reranker-v2-m3@953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
    )
    assert reranked_run.metadata.candidate_limit == 4
    assert reranked_run.metadata.final_limit == 2
    assert reranked_run.cases[0].candidate_count == 4
    assert reranked_run.cases[0].final_candidate_count == 2
    assert reranked_run.mean_latency_ms > 0
    assert reranked_run.p50_latency_ms > 0
    assert reranked_run.p95_latency_ms > 0
    assert all(
        candidate.dense_score is not None
        for case in hybrid_run.cases
        for candidate in case.ranked_candidates
    )
    first = reranked_run.cases[0].ranked_candidates[0]
    assert first.reranker_score is not None
    assert first.candidate.provenance.document_version
    assert first.candidate.provenance.locator
    assert embedding_backend.closed is True
    assert reranker_backend.closed is True


def test_error_slices_use_only_explicit_gold_tags():
    dataset = load_dataset(FIXTURE, checked_in=True)
    result = run_semantic_matrix(
        dataset,
        _test_configuration(),
        code_version="test-commit",
        embedding_backend=RecordingEmbeddingBackend(),
        reranker_backend=RecordingCrossEncoderBackend(prefer_hard_negatives=True),
        timer_ns=_timer(),
    )
    cross = next(
        method
        for method in result.error_analysis.methods
        if method.method_label == "hybrid_cross_encoder"
    )
    slices = {item.label: item for item in cross.slices}

    assert slices[ErrorSliceLabel.HARD_NEGATIVE_ABOVE_POSITIVE].error_query_count == 2
    assert slices[ErrorSliceLabel.WRONG_PRODUCT_VERSION].error_query_count == 1
    assert slices[ErrorSliceLabel.OBSOLETE_SOURCE].error_query_count == 1
    assert slices[ErrorSliceLabel.NON_ENTAILING].error_query_count == 1
    assert slices[ErrorSliceLabel.ROADMAP_NOT_RELEASED].eligible_query_count == 0
    assert slices[ErrorSliceLabel.TEMPORAL_VALIDITY].eligible_query_count == 0
    assert slices[ErrorSliceLabel.SOURCE_AUTHORITY].eligible_query_count == 0


def test_test_dataset_cannot_be_reused_for_rrf_tuning():
    dataset = load_dataset(FIXTURE, checked_in=True)
    configuration = _test_configuration()
    digest = dataset_sha256(dataset)
    leakage = configuration.leakage.model_copy(
        update={
            "rrf_weight_source": RRFWeightSource.DEVELOPMENT_TUNED,
            "development_dataset_sha256": digest,
        }
    )
    leaking = configuration.model_copy(update={"leakage": leakage})

    with pytest.raises(ValueError, match="cannot also be the RRF tuning dataset"):
        leaking.assert_no_test_leakage(digest)


def test_cross_encoder_rejects_nonfinite_scores_and_preserves_candidate_identity():
    dataset = load_dataset(FIXTURE, checked_in=True)
    problem = build_retrieval_problem(dataset)
    query = problem.judgments[0].query
    configuration = _test_configuration()
    dense = DenseRetriever(
        problem.corpus,
        E5EmbeddingModel(configuration.embedding, backend=RecordingEmbeddingBackend()),
    )
    candidates = dense.retrieve(query, limit=2)
    reranker = CrossEncoderReranker(
        configuration.reranker,
        backend=RecordingCrossEncoderBackend(),
    )

    reranked = reranker.rerank(query, candidates, limit=2)

    provenance_by_id = {
        item.candidate.evidence_span_id: item.candidate.provenance for item in candidates
    }
    assert {item.candidate.evidence_span_id for item in reranked} == {
        item.candidate.evidence_span_id for item in candidates
    }
    assert all(
        item.candidate.provenance == provenance_by_id[item.candidate.evidence_span_id]
        for item in reranked
    )

    nonfinite = CrossEncoderReranker(
        configuration.reranker,
        backend=NonFiniteCrossEncoderBackend(),
    )
    with pytest.raises(NeuralModelError, match="non-finite"):
        nonfinite.rerank(query, candidates, limit=2)
