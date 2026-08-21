from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ctrl_v2.evaluation.gold_dataset import GoldComplianceLabel


class ComparisonModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, protected_namespaces=()
    )


class IntelligenceSystemVariant(StrEnum):
    HUMAN_MANUAL = "HUMAN_MANUAL"
    HUMAN_GENERAL_LLM = "HUMAN_GENERAL_LLM"
    CTRL_PIPELINE = "CTRL_PIPELINE"


class IntelligenceComparisonRecord(ComparisonModel):
    schema_version: Literal["1.0"] = "1.0"
    case_id: str = Field(min_length=1)
    system_variant: IntelligenceSystemVariant
    predicted_atomic_requirement_keys: tuple[str, ...]
    predicted_evidence_span_ids: tuple[str, ...]
    predicted_decision: GoldComplianceLabel
    wrong_version_error: bool
    conflict_detected: bool
    human_correction: GoldComplianceLabel | None = None
    latency_ms: float = Field(ge=0)
    cost: float | None = Field(default=None, ge=0)
    cost_currency: str | None = None
    provider: str | None = None
    model_id: str | None = None
