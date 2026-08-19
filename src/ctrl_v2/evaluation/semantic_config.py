from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .neural_models import CrossEncoderConfig, E5EmbeddingConfig, NeuralConfigModel
from .retrieval import HybridConfig


class DatasetSplit(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    TEST = "TEST"


class RRFWeightSource(StrEnum):
    FIXED_BASELINE = "FIXED_BASELINE"
    DEVELOPMENT_TUNED = "DEVELOPMENT_TUNED"


class LeakagePolicy(NeuralConfigModel):
    dataset_split: DatasetSplit
    configuration_frozen_before_test: bool
    rrf_weight_source: RRFWeightSource
    development_dataset_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    positives_usage: Literal["EVALUATION_ONLY"] = "EVALUATION_ONLY"
    hard_negatives_usage: Literal["EVALUATION_ONLY"] = "EVALUATION_ONLY"

    @model_validator(mode="after")
    def validate_weight_source(self) -> LeakagePolicy:
        if (
            self.rrf_weight_source == RRFWeightSource.DEVELOPMENT_TUNED
            and self.development_dataset_sha256 is None
        ):
            raise ValueError("development-tuned RRF weights require a development dataset hash")
        if self.dataset_split == DatasetSplit.TEST and not self.configuration_frozen_before_test:
            raise ValueError("test evaluation requires frozen configuration")
        return self


class SemanticExperimentConfig(NeuralConfigModel):
    schema_version: Literal["1.0"] = "1.0"
    embedding: E5EmbeddingConfig
    reranker: CrossEncoderConfig
    candidate_n: int = Field(gt=0)
    final_k: int = Field(gt=0)
    random_seed: int = 0
    lexical_weight: float = Field(default=1.0, ge=0)
    dense_weight: float = Field(default=1.0, ge=0)
    rrf_k: int = Field(default=60, gt=0)
    leakage: LeakagePolicy

    @model_validator(mode="after")
    def validate_limits(self) -> SemanticExperimentConfig:
        if self.final_k > self.candidate_n:
            raise ValueError("final_k cannot exceed candidate_n")
        if not self.lexical_weight and not self.dense_weight:
            raise ValueError("at least one hybrid weight must be positive")
        return self

    def hybrid_config(self) -> HybridConfig:
        return HybridConfig(
            lexical_weight=self.lexical_weight,
            dense_weight=self.dense_weight,
            rrf_k=self.rrf_k,
        )

    def assert_no_test_leakage(self, dataset_sha256: str) -> None:
        development_hash = self.leakage.development_dataset_sha256
        if self.leakage.dataset_split == DatasetSplit.TEST and development_hash == dataset_sha256:
            raise ValueError("test dataset cannot also be the RRF tuning dataset")


def load_semantic_config(path: Path) -> SemanticExperimentConfig:
    return SemanticExperimentConfig.model_validate_json(path.read_text(encoding="utf-8"))
