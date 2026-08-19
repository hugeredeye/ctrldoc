from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ctrl_v2.application.structured_contracts import SourceLocator
from ctrl_v2.domain.enums import EvidenceAuthorityLevel, EvidenceSourceType

JsonScalar = str | int | float | bool | None


class RetrievalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EvidenceSpanProvenance(RetrievalModel):
    asset_path: str = Field(min_length=1)
    document_key: str = Field(min_length=1)
    document_version: str = Field(min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    locator: SourceLocator
    source_type: EvidenceSourceType
    authority_level: EvidenceAuthorityLevel
    valid_from: date
    valid_to: date | None = None
    product_version_key: str | None = None

    @model_validator(mode="after")
    def validate_temporal_scope(self) -> EvidenceSpanProvenance:
        if self.valid_to is not None and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not be after valid_to")
        return self


class EvidenceSpanCandidate(RetrievalModel):
    evidence_span_id: str = Field(min_length=1)
    canonical_text: str = Field(min_length=1)
    provenance: EvidenceSpanProvenance


class RetrievalQuery(RetrievalModel):
    query_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    atomic_requirement_key: str = Field(min_length=1)
    requirement_text: str = Field(min_length=1)
    source_context: str | None = None


class RetrievedEvidenceSpan(RetrievalModel):
    candidate: EvidenceSpanCandidate
    rank: int = Field(ge=1)
    score: float
    method: str = Field(min_length=1)
    lexical_score: float | None = None
    dense_score: float | None = None
    reranker_score: float | None = None

    @model_validator(mode="after")
    def validate_scores(self) -> RetrievedEvidenceSpan:
        values = (self.score, self.lexical_score, self.dense_score, self.reranker_score)
        if any(value is not None and not math.isfinite(value) for value in values):
            raise ValueError("retrieval scores must be finite")
        return self


@runtime_checkable
class EmbeddingModel(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def parameters(self) -> Mapping[str, JsonScalar]: ...

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@runtime_checkable
class AsymmetricEmbeddingModel(EmbeddingModel, Protocol):
    def embed_queries(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


@runtime_checkable
class EvidenceRetriever(Protocol):
    @property
    def method(self) -> str: ...

    @property
    def implementation_id(self) -> str: ...

    @property
    def embedding_model_id(self) -> str | None: ...

    @property
    def parameters(self) -> Mapping[str, JsonScalar]: ...

    @property
    def candidate_count(self) -> int: ...

    def retrieve(
        self, query: RetrievalQuery, *, limit: int
    ) -> tuple[RetrievedEvidenceSpan, ...]: ...


@runtime_checkable
class EvidenceReranker(Protocol):
    @property
    def implementation_id(self) -> str: ...

    @property
    def model_id(self) -> str | None: ...

    @property
    def parameters(self) -> Mapping[str, JsonScalar]: ...

    def rerank(
        self,
        query: RetrievalQuery,
        candidates: Sequence[RetrievedEvidenceSpan],
        *,
        limit: int,
    ) -> tuple[RetrievedEvidenceSpan, ...]: ...
