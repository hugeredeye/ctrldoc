from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .gold_dataset import GoldComplianceLabel
from .retrieval_contracts import RetrievalQuery, RetrievedEvidenceSpan


class ResearchTraceModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, protected_namespaces=()
    )


class ResearchActionType(StrEnum):
    EXTRACT = "EXTRACT"
    MAP = "MAP"
    RETRIEVE = "RETRIEVE"
    RETRIEVE_MORE = "RETRIEVE_MORE"
    RERANK = "RERANK"
    VERIFY = "VERIFY"
    ABSTAIN = "ABSTAIN"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"
    SELECT_DECISION = "SELECT_DECISION"


class ResearchMappingState(ResearchTraceModel):
    product_id: str | None = None
    product_version_id: str | None = None
    capability_id: str | None = None
    disposition: str
    score: float | None = Field(default=None, ge=0, le=1)


class ResearchVerificationState(ResearchTraceModel):
    evidence_span_id: str
    provider_label: str
    effective_label: str
    reason_tags: tuple[str, ...] = ()


class ResearchState(ResearchTraceModel):
    requirement: RetrievalQuery
    retrieved_candidates: tuple[RetrievedEvidenceSpan, ...]
    mapping_candidates: tuple[ResearchMappingState, ...] = ()
    verifier_outputs: tuple[ResearchVerificationState, ...] = ()
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
    providers: tuple[str, ...] = ()
    model_ids: tuple[str, ...] = ()
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class ResearchTrace(ResearchTraceModel):
    schema_version: Literal["1.0"] = "1.0"
    trace_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    occurred_at: datetime
    state: ResearchState
    action: ResearchAction
    outcome: ResearchOutcome
