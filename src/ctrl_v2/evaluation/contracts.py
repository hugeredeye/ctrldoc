from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ctrl_v2.domain.enums import ComplianceOutcome


class EvalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationVersions(EvalModel):
    dataset: str
    parser: str
    extraction_contract: str
    extraction_prompt: str
    model: str
    retrieval: str
    decision_prompt: str
    conflict_prompt: str


class ExtractionCase(EvalModel):
    case_id: str
    expected_requirement_keys: set[str]
    predicted_requirement_keys: set[str]


class RetrievalCase(EvalModel):
    case_id: str
    expected_evidence_span_ids: set[str]
    ranked_evidence_span_ids: list[str]
    k: int = Field(gt=0)


class DecisionCase(EvalModel):
    case_id: str
    expected: ComplianceOutcome
    predicted: ComplianceOutcome
    human_approved_without_edit: bool


class ConflictCase(EvalModel):
    case_id: str
    is_critical: bool
    expected_conflict: bool
    predicted_conflict: bool
    decision: ComplianceOutcome


class EvaluationFixture(EvalModel):
    schema_version: Literal["1.0"] = "1.0"
    versions: EvaluationVersions
    extraction: list[ExtractionCase] = []
    retrieval: list[RetrievalCase] = []
    decisions: list[DecisionCase] = []
    conflicts: list[ConflictCase] = []
