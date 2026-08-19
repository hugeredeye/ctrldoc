from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .retrieval_contracts import (
    AsymmetricEmbeddingModel,
    EmbeddingModel,
    EvidenceSpanCandidate,
    JsonScalar,
    RetrievalQuery,
    RetrievedEvidenceSpan,
)

_TOKEN_PATTERN = re.compile(r"\b[\w-]+\b", re.UNICODE)


def tokenize(text: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _TOKEN_PATTERN.findall(text))


def _validated_candidates(
    candidates: Sequence[EvidenceSpanCandidate],
) -> tuple[EvidenceSpanCandidate, ...]:
    result = tuple(candidates)
    identifiers = [candidate.evidence_span_id for candidate in result]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("candidate evidence_span_id values must be unique")
    if not result:
        raise ValueError("retrieval corpus cannot be empty")
    return result


@dataclass(frozen=True, slots=True)
class BM25Config:
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        if self.k1 <= 0:
            raise ValueError("BM25 k1 must be positive")
        if not 0 <= self.b <= 1:
            raise ValueError("BM25 b must be between zero and one")


class BM25Retriever:
    method = "lexical"
    implementation_id = "okapi-bm25-v1"
    embedding_model_id = None

    def __init__(
        self,
        candidates: Sequence[EvidenceSpanCandidate],
        config: BM25Config | None = None,
    ) -> None:
        self._candidates = _validated_candidates(candidates)
        self._config = config or BM25Config()
        self._tokens = tuple(tokenize(item.canonical_text) for item in self._candidates)
        self._term_frequencies = tuple(Counter(tokens) for tokens in self._tokens)
        self._document_lengths = tuple(len(tokens) for tokens in self._tokens)
        self._average_document_length = sum(self._document_lengths) / len(self._document_lengths)
        self._document_frequencies = Counter(
            token for tokens in self._tokens for token in set(tokens)
        )

    @property
    def parameters(self) -> Mapping[str, JsonScalar]:
        return {"k1": self._config.k1, "b": self._config.b, "tokenizer": "unicode-word-v1"}

    @property
    def candidate_count(self) -> int:
        return len(self._candidates)

    def retrieve(self, query: RetrievalQuery, *, limit: int) -> tuple[RetrievedEvidenceSpan, ...]:
        if limit <= 0:
            raise ValueError("retrieval limit must be positive")
        query_terms = tokenize(query.requirement_text)
        document_count = len(self._candidates)
        scored: list[tuple[float, EvidenceSpanCandidate]] = []
        for candidate, frequencies, document_length in zip(
            self._candidates,
            self._term_frequencies,
            self._document_lengths,
            strict=True,
        ):
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequencies[term]
                inverse_document_frequency = math.log(
                    1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                normalization = frequency + self._config.k1 * (
                    1
                    - self._config.b
                    + self._config.b * document_length / max(self._average_document_length, 1.0)
                )
                score += inverse_document_frequency * (
                    frequency * (self._config.k1 + 1) / normalization
                )
            scored.append((score, candidate))
        scored.sort(key=lambda item: (-item[0], item[1].evidence_span_id))
        return tuple(
            RetrievedEvidenceSpan(
                candidate=candidate,
                rank=rank,
                score=score,
                lexical_score=score,
                method=self.method,
            )
            for rank, (score, candidate) in enumerate(scored[:limit], start=1)
        )


@dataclass(frozen=True, slots=True)
class HashingEmbeddingConfig:
    dimensions: int = 256
    include_bigrams: bool = True
    model_id: str = "ctrl-feature-hashing-document-embedding-v1"

    def __post_init__(self) -> None:
        if self.dimensions <= 0:
            raise ValueError("embedding dimensions must be positive")
        if not self.model_id:
            raise ValueError("embedding model_id cannot be empty")


class HashingEmbeddingModel:
    """Deterministic dependency-free document embedding baseline, not a semantic ML model."""

    def __init__(self, config: HashingEmbeddingConfig | None = None) -> None:
        self._config = config or HashingEmbeddingConfig()

    @property
    def model_id(self) -> str:
        return self._config.model_id

    @property
    def parameters(self) -> Mapping[str, JsonScalar]:
        return {
            "dimensions": self._config.dimensions,
            "include_bigrams": self._config.include_bigrams,
            "tokenizer": "unicode-word-v1",
        }

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return tuple(self._embed_one(text) for text in texts)

    def _embed_one(self, text: str) -> tuple[float, ...]:
        tokens = tokenize(text)
        features = list(tokens)
        if self._config.include_bigrams:
            features.extend(
                f"{left}\u241f{right}" for left, right in zip(tokens, tokens[1:], strict=False)
            )
        vector = [0.0] * self._config.dimensions
        for feature in features:
            digest = hashlib.blake2b(
                feature.encode("utf-8"), digest_size=8, person=b"ctrl-v2-embed"
            ).digest()
            value = int.from_bytes(digest, "big")
            index = value % self._config.dimensions
            sign = 1.0 if value & (1 << 63) else -1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return tuple(vector)


def _validate_embeddings(
    vectors: Sequence[Sequence[float]], expected_count: int
) -> tuple[tuple[float, ...], ...]:
    normalized = tuple(tuple(vector) for vector in vectors)
    if len(normalized) != expected_count:
        raise ValueError("embedding model returned an unexpected vector count")
    dimensions = {len(vector) for vector in normalized}
    if len(dimensions) != 1 or not dimensions or next(iter(dimensions)) <= 0:
        raise ValueError("embedding vectors must share a positive dimension")
    if any(not math.isfinite(value) for vector in normalized for value in vector):
        raise ValueError("embedding vectors must contain only finite values")
    return normalized


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


class DenseRetriever:
    method = "dense"
    implementation_id = "cosine-dense-retrieval-v1"

    def __init__(
        self,
        candidates: Sequence[EvidenceSpanCandidate],
        embedding_model: EmbeddingModel,
    ) -> None:
        self._candidates = _validated_candidates(candidates)
        self._embedding_model = embedding_model
        embed_documents = (
            embedding_model.embed_documents
            if isinstance(embedding_model, AsymmetricEmbeddingModel)
            else embedding_model.embed
        )
        self._candidate_vectors = _validate_embeddings(
            embed_documents([candidate.canonical_text for candidate in self._candidates]),
            len(self._candidates),
        )

    @property
    def embedding_model_id(self) -> str:
        return self._embedding_model.model_id

    @property
    def parameters(self) -> Mapping[str, JsonScalar]:
        return {
            "similarity": "cosine",
            **{
                f"embedding.{key}": value for key, value in self._embedding_model.parameters.items()
            },
        }

    @property
    def candidate_count(self) -> int:
        return len(self._candidates)

    def retrieve(self, query: RetrievalQuery, *, limit: int) -> tuple[RetrievedEvidenceSpan, ...]:
        if limit <= 0:
            raise ValueError("retrieval limit must be positive")
        embed_queries = (
            self._embedding_model.embed_queries
            if isinstance(self._embedding_model, AsymmetricEmbeddingModel)
            else self._embedding_model.embed
        )
        query_vector = _validate_embeddings(embed_queries([query.requirement_text]), 1)[0]
        if len(query_vector) != len(self._candidate_vectors[0]):
            raise ValueError("query and candidate embedding dimensions differ")
        scored = [
            (_cosine_similarity(query_vector, vector), candidate)
            for candidate, vector in zip(self._candidates, self._candidate_vectors, strict=True)
        ]
        scored.sort(key=lambda item: (-item[0], item[1].evidence_span_id))
        return tuple(
            RetrievedEvidenceSpan(
                candidate=candidate,
                rank=rank,
                score=score,
                dense_score=score,
                method=self.method,
            )
            for rank, (score, candidate) in enumerate(scored[:limit], start=1)
        )


@dataclass(frozen=True, slots=True)
class HybridConfig:
    lexical_weight: float = 1.0
    dense_weight: float = 1.0
    rrf_k: int = 60

    def __post_init__(self) -> None:
        if self.lexical_weight < 0 or self.dense_weight < 0:
            raise ValueError("hybrid weights cannot be negative")
        if not self.lexical_weight and not self.dense_weight:
            raise ValueError("at least one hybrid weight must be positive")
        if self.rrf_k <= 0:
            raise ValueError("RRF k must be positive")


class HybridRetriever:
    method = "hybrid"
    implementation_id = "weighted-rrf-v1"

    def __init__(
        self,
        lexical: BM25Retriever,
        dense: DenseRetriever,
        config: HybridConfig | None = None,
    ) -> None:
        if lexical.candidate_count != dense.candidate_count:
            raise ValueError("hybrid retrievers must use the same candidate corpus")
        self._lexical = lexical
        self._dense = dense
        self._config = config or HybridConfig()

    @property
    def embedding_model_id(self) -> str:
        return self._dense.embedding_model_id

    @property
    def parameters(self) -> Mapping[str, JsonScalar]:
        return {
            "lexical_weight": self._config.lexical_weight,
            "dense_weight": self._config.dense_weight,
            "rrf_k": self._config.rrf_k,
            "lexical_implementation": self._lexical.implementation_id,
            "dense_implementation": self._dense.implementation_id,
        }

    @property
    def candidate_count(self) -> int:
        return self._lexical.candidate_count

    def retrieve(self, query: RetrievalQuery, *, limit: int) -> tuple[RetrievedEvidenceSpan, ...]:
        if limit <= 0:
            raise ValueError("retrieval limit must be positive")
        lexical_results = self._lexical.retrieve(query, limit=self.candidate_count)
        dense_results = self._dense.retrieve(query, limit=self.candidate_count)
        lexical_by_id = {result.candidate.evidence_span_id: result for result in lexical_results}
        dense_by_id = {result.candidate.evidence_span_id: result for result in dense_results}
        scored: list[tuple[float, EvidenceSpanCandidate, float, float]] = []
        for evidence_span_id, lexical_result in lexical_by_id.items():
            dense_result = dense_by_id[evidence_span_id]
            score = self._config.lexical_weight / (
                self._config.rrf_k + lexical_result.rank
            ) + self._config.dense_weight / (self._config.rrf_k + dense_result.rank)
            scored.append(
                (
                    score,
                    lexical_result.candidate,
                    lexical_result.score,
                    dense_result.score,
                )
            )
        scored.sort(key=lambda item: (-item[0], item[1].evidence_span_id))
        return tuple(
            RetrievedEvidenceSpan(
                candidate=candidate,
                rank=rank,
                score=score,
                lexical_score=lexical_score,
                dense_score=dense_score,
                method=self.method,
            )
            for rank, (score, candidate, lexical_score, dense_score) in enumerate(
                scored[:limit], start=1
            )
        )


class IdentityReranker:
    implementation_id = "identity-reranker-v1"
    model_id = None

    @property
    def parameters(self) -> Mapping[str, JsonScalar]:
        return {}

    def rerank(
        self,
        query: RetrievalQuery,
        candidates: Sequence[RetrievedEvidenceSpan],
        *,
        limit: int,
    ) -> tuple[RetrievedEvidenceSpan, ...]:
        del query
        if limit <= 0:
            raise ValueError("reranking limit must be positive")
        return tuple(
            candidate.model_copy(update={"rank": rank})
            for rank, candidate in enumerate(candidates[:limit], start=1)
        )
