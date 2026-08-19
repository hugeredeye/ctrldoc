from __future__ import annotations

import gc
import hashlib
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .retrieval_contracts import (
    JsonScalar,
    RetrievalQuery,
    RetrievedEvidenceSpan,
)


class NeuralModelError(RuntimeError):
    pass


class NeuralModelLoadError(NeuralModelError):
    pass


class ModelArtifactIntegrityError(NeuralModelError):
    pass


class NeuralConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ModelArtifactIdentity(NeuralConfigModel):
    model_name: str = Field(min_length=1)
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    weights_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class E5EmbeddingConfig(NeuralConfigModel):
    artifact: ModelArtifactIdentity
    embedding_dimension: int = Field(gt=0)
    query_instruction: str = Field(min_length=1)
    normalize_embeddings: bool = True
    batch_size: int = Field(default=8, gt=0)
    max_length: int = Field(default=512, gt=0)
    device: str = Field(default="cpu", min_length=1)
    torch_dtype: Literal["float32"] = "float32"
    offline: bool = True
    cache_dir: Path | None = None
    local_path: Path | None = None


class CrossEncoderConfig(NeuralConfigModel):
    artifact: ModelArtifactIdentity
    batch_size: int = Field(default=4, gt=0)
    max_length: int = Field(default=512, gt=0)
    device: str = Field(default="cpu", min_length=1)
    torch_dtype: Literal["float32"] = "float32"
    score_activation: Literal["sigmoid", "identity"] = "sigmoid"
    offline: bool = True
    cache_dir: Path | None = None
    local_path: Path | None = None


class SentenceEmbeddingBackend(Protocol):
    @property
    def dimension(self) -> int: ...

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int,
        normalize: bool,
    ) -> Sequence[Sequence[float]]: ...

    def close(self) -> None: ...


class CrossEncoderBackend(Protocol):
    def score(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        max_length: int,
    ) -> Sequence[float]: ...

    def close(self) -> None: ...


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_verified_snapshot(
    artifact: ModelArtifactIdentity,
    *,
    offline: bool,
    cache_dir: Path | None,
    local_path: Path | None,
) -> Path:
    if local_path is not None:
        snapshot = local_path.expanduser().resolve()
    else:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise NeuralModelLoadError(
                "huggingface-hub research dependency is not installed"
            ) from exc
        try:
            snapshot = Path(
                snapshot_download(
                    repo_id=artifact.model_name,
                    revision=artifact.revision,
                    cache_dir=str(cache_dir) if cache_dir else None,
                    local_files_only=offline,
                )
            ).resolve()
        except Exception as exc:
            mode = "offline/local" if offline else "online"
            raise NeuralModelLoadError(
                f"Cannot load pinned model {artifact.model_name}@{artifact.revision} in {mode} mode"
            ) from exc

    weights = snapshot / "model.safetensors"
    config = snapshot / "config.json"
    if not weights.is_file() or not config.is_file():
        raise NeuralModelLoadError(
            f"Pinned model snapshot is incomplete: {artifact.model_name}@{artifact.revision}"
        )
    actual_weights = _sha256(weights)
    actual_config = _sha256(config)
    if actual_weights != artifact.weights_sha256 or actual_config != artifact.config_sha256:
        raise ModelArtifactIntegrityError(
            f"Pinned model artifact identity mismatch: {artifact.model_name}@{artifact.revision}"
        )
    return snapshot


class SentenceTransformerBackend:
    def __init__(self, config: E5EmbeddingConfig) -> None:
        snapshot = _resolve_verified_snapshot(
            config.artifact,
            offline=config.offline,
            cache_dir=config.cache_dir,
            local_path=config.local_path,
        )
        try:
            import torch
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(
                str(snapshot),
                device=config.device,
                local_files_only=True,
                model_kwargs={"torch_dtype": torch.float32},
            )
            self._model.max_seq_length = config.max_length
        except ImportError as exc:
            raise NeuralModelLoadError(
                "sentence-transformers and CPU PyTorch research dependencies are required"
            ) from exc
        except Exception as exc:
            raise NeuralModelLoadError(
                f"Failed to load embedding model {config.artifact.model_name}"
            ) from exc
        dimension = self._model.get_sentence_embedding_dimension()
        if dimension != config.embedding_dimension:
            self.close()
            raise NeuralModelLoadError(
                "Embedding dimension mismatch: "
                f"expected {config.embedding_dimension}, got {dimension}"
            )
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def encode(
        self,
        texts: Sequence[str],
        *,
        batch_size: int,
        normalize: bool,
    ) -> Sequence[Sequence[float]]:
        vectors = self._model.encode(
            list(texts),
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=normalize,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def close(self) -> None:
        model = getattr(self, "_model", None)
        if model is not None:
            del self._model
        gc.collect()


class TransformersCrossEncoderBackend:
    def __init__(self, config: CrossEncoderConfig) -> None:
        snapshot = _resolve_verified_snapshot(
            config.artifact,
            offline=config.offline,
            cache_dir=config.cache_dir,
            local_path=config.local_path,
        )
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._torch = torch
            self._tokenizer = AutoTokenizer.from_pretrained(str(snapshot), local_files_only=True)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                str(snapshot),
                local_files_only=True,
                torch_dtype=torch.float32,
            ).to(config.device)
            self._model.eval()
            self._device = config.device
        except ImportError as exc:
            raise NeuralModelLoadError(
                "transformers and CPU PyTorch research dependencies are required"
            ) from exc
        except Exception as exc:
            raise NeuralModelLoadError(
                f"Failed to load reranker model {config.artifact.model_name}"
            ) from exc

    def score(
        self,
        pairs: Sequence[tuple[str, str]],
        *,
        batch_size: int,
        max_length: int,
    ) -> Sequence[float]:
        scores: list[float] = []
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            inputs = self._tokenizer(
                list(batch),
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            inputs = {name: value.to(self._device) for name, value in inputs.items()}
            with self._torch.no_grad():
                logits = self._model(**inputs).logits.view(-1)
            scores.extend(float(value) for value in logits.cpu())
        return scores

    def close(self) -> None:
        for attribute in ("_model", "_tokenizer"):
            if hasattr(self, attribute):
                delattr(self, attribute)
        gc.collect()


class E5EmbeddingModel:
    def __init__(
        self,
        config: E5EmbeddingConfig,
        backend: SentenceEmbeddingBackend | None = None,
    ) -> None:
        self.config = config
        self._backend = backend
        self._closed = False

    @property
    def model_id(self) -> str:
        return f"{self.config.artifact.model_name}@{self.config.artifact.revision}"

    @property
    def parameters(self) -> Mapping[str, JsonScalar]:
        return {
            "model_name": self.config.artifact.model_name,
            "model_revision": self.config.artifact.revision,
            "weights_sha256": self.config.artifact.weights_sha256,
            "config_sha256": self.config.artifact.config_sha256,
            "embedding_dimension": self.config.embedding_dimension,
            "normalize_embeddings": self.config.normalize_embeddings,
            "query_preprocessing": "Instruct: {instruction}\\nQuery: {requirement}",
            "document_preprocessing": "strip-only; no instruction",
            "query_instruction": self.config.query_instruction,
            "batch_size": self.config.batch_size,
            "max_length": self.config.max_length,
            "device": self.config.device,
            "torch_dtype": self.config.torch_dtype,
            "offline": self.config.offline,
        }

    def preprocess_query(self, text: str) -> str:
        requirement = text.strip()
        if not requirement:
            raise ValueError("E5 query cannot be blank")
        return f"Instruct: {self.config.query_instruction}\nQuery: {requirement}"

    @staticmethod
    def preprocess_document(text: str) -> str:
        document = text.strip()
        if not document:
            raise ValueError("E5 document cannot be blank")
        return document

    def _get_backend(self) -> SentenceEmbeddingBackend:
        if self._closed:
            raise NeuralModelLoadError("Embedding model has been closed")
        if self._backend is None:
            self._backend = SentenceTransformerBackend(self.config)
        if self._backend.dimension != self.config.embedding_dimension:
            raise NeuralModelLoadError("Configured embedding dimension does not match loaded model")
        return self._backend

    def embed(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return self.embed_documents(texts)

    def embed_queries(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        prepared = [self.preprocess_query(text) for text in texts]
        return self._get_backend().encode(
            prepared,
            batch_size=self.config.batch_size,
            normalize=self.config.normalize_embeddings,
        )

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        prepared = [self.preprocess_document(text) for text in texts]
        return self._get_backend().encode(
            prepared,
            batch_size=self.config.batch_size,
            normalize=self.config.normalize_embeddings,
        )

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        self._closed = True


def _activate(score: float, activation: str) -> float:
    if activation == "identity":
        return score
    if score >= 0:
        return 1.0 / (1.0 + math.exp(-score))
    exponential = math.exp(score)
    return exponential / (1.0 + exponential)


class CrossEncoderReranker:
    implementation_id = "transformers-cross-encoder-v1"

    def __init__(
        self,
        config: CrossEncoderConfig,
        backend: CrossEncoderBackend | None = None,
    ) -> None:
        self.config = config
        self._backend = backend
        self._closed = False

    @property
    def model_id(self) -> str:
        return f"{self.config.artifact.model_name}@{self.config.artifact.revision}"

    @property
    def parameters(self) -> Mapping[str, JsonScalar]:
        return {
            "model_name": self.config.artifact.model_name,
            "model_revision": self.config.artifact.revision,
            "weights_sha256": self.config.artifact.weights_sha256,
            "config_sha256": self.config.artifact.config_sha256,
            "batch_size": self.config.batch_size,
            "max_length": self.config.max_length,
            "device": self.config.device,
            "torch_dtype": self.config.torch_dtype,
            "score_activation": self.config.score_activation,
            "pair_preprocessing": "tokenizer(query, evidence_text)",
            "offline": self.config.offline,
        }

    def _get_backend(self) -> CrossEncoderBackend:
        if self._closed:
            raise NeuralModelLoadError("Cross-encoder model has been closed")
        if self._backend is None:
            self._backend = TransformersCrossEncoderBackend(self.config)
        return self._backend

    def rerank(
        self,
        query: RetrievalQuery,
        candidates: Sequence[RetrievedEvidenceSpan],
        *,
        limit: int,
    ) -> tuple[RetrievedEvidenceSpan, ...]:
        if limit <= 0:
            raise ValueError("reranking limit must be positive")
        if not candidates:
            return ()
        pairs = tuple(
            (query.requirement_text, candidate.candidate.canonical_text) for candidate in candidates
        )
        raw_scores = tuple(
            self._get_backend().score(
                pairs,
                batch_size=self.config.batch_size,
                max_length=self.config.max_length,
            )
        )
        if len(raw_scores) != len(candidates):
            raise NeuralModelError("Cross-encoder returned an unexpected score count")
        activated = tuple(_activate(score, self.config.score_activation) for score in raw_scores)
        if any(not math.isfinite(score) for score in activated):
            raise NeuralModelError("Cross-encoder returned a non-finite score")
        scored = sorted(
            zip(activated, candidates, strict=True),
            key=lambda item: (-item[0], item[1].candidate.evidence_span_id),
        )
        return tuple(
            candidate.model_copy(
                update={
                    "rank": rank,
                    "score": score,
                    "reranker_score": score,
                    "method": f"{candidate.method}+cross-encoder",
                }
            )
            for rank, (score, candidate) in enumerate(scored[:limit], start=1)
        )

    def close(self) -> None:
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        self._closed = True
