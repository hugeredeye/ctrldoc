from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .gold_dataset import GoldComplianceLabel
from .retrieval_contracts import RetrievalQuery, RetrievedEvidenceSpan


class ResearchTraceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ResearchActionType(StrEnum):
    RETRIEVE_MORE = "RETRIEVE_MORE"
    RERANK = "RERANK"
    VERIFY = "VERIFY"
    ABSTAIN = "ABSTAIN"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"
    SELECT_DECISION = "SELECT_DECISION"


class ResearchState(ResearchTraceModel):
    requirement: RetrievalQuery
    retrieved_candidates: tuple[RetrievedEvidenceSpan, ...]
    conflicts: tuple[str, ...] = ()
    uncertainty: float | None = Field(default=None, ge=0, le=1)


class ResearchAction(ResearchTraceModel):
    action: ResearchActionType
    selected_evidence_span_ids: tuple[str, ...] = ()
    selected_decision: GoldComplianceLabel | None = None
    requested_candidate_count: int | None = Field(default=None, gt=0)
    rationale: str | None = None


class ResearchOutcome(ResearchTraceModel):
    model_decision: GoldComplianceLabel | None = None
    human_correction: GoldComplianceLabel | None = None
    accepted: bool | None = None
    latency_ms: float = Field(ge=0)
    inference_cost: float | None = Field(default=None, ge=0)
    tool_cost: float | None = Field(default=None, ge=0)
    cost_currency: str | None = None


class ResearchTrace(ResearchTraceModel):
    schema_version: Literal["1.0"] = "1.0"
    trace_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    occurred_at: datetime
    state: ResearchState
    action: ResearchAction
    outcome: ResearchOutcome
