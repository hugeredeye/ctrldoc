from __future__ import annotations

from datetime import datetime

from ctrl_v2.evaluation.gold_dataset import GoldComplianceLabel
from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicIntelligenceResult,
    GuardedComplianceStatus,
    ModelCallRecord,
)
from ctrl_v2.evaluation.research_trace import (
    ResearchAction,
    ResearchActionType,
    ResearchMappingState,
    ResearchOutcome,
    ResearchState,
    ResearchTrace,
    ResearchVerificationState,
)
from ctrl_v2.evaluation.retrieval_contracts import RetrievalQuery


def _sum_optional(values: list[int | None]) -> int | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _research_state(
    result: AtomicIntelligenceResult,
    *,
    include_mapping: bool,
    include_evidence: bool,
    include_verifications: bool,
) -> ResearchState:
    query = RetrievalQuery(
        query_id=f"{result.original_requirement.requirement_id}:{result.atomic_requirement.atomic_id}",
        case_id=result.original_requirement.requirement_id,
        atomic_requirement_key=result.atomic_requirement.atomic_id,
        requirement_text=result.atomic_requirement.normalized_text,
        source_context=result.original_requirement.source_context,
    )
    return ResearchState(
        requirement=query,
        retrieved_candidates=result.candidate_evidence if include_evidence else (),
        mapping_candidates=(
            tuple(
                ResearchMappingState(
                    product_id=item.product_id,
                    product_version_id=item.product_version_id,
                    capability_id=item.capability_id,
                    disposition=item.disposition.value,
                    score=item.score,
                )
                for item in result.mapping.candidates
            )
            if include_mapping
            else ()
        ),
        verifier_outputs=(
            tuple(
                ResearchVerificationState(
                    evidence_span_id=item.evidence_span_id,
                    provider_label=item.provider_output.label.value,
                    effective_label=item.effective_output.label.value,
                    reason_tags=tuple(tag.value for tag in item.effective_output.reason_tags),
                )
                for item in result.verifications
            )
            if include_verifications
            else ()
        ),
        conflicts=result.conflict.evidence_span_ids if include_verifications else (),
    )


def _research_outcome(
    calls: tuple[ModelCallRecord, ...],
    *,
    decision: GoldComplianceLabel | None = None,
    human_correction: GoldComplianceLabel | None = None,
    accepted: bool | None = None,
) -> ResearchOutcome:
    estimated_costs = [call.estimated_cost for call in calls if call.estimated_cost is not None]
    cost_currencies = {call.cost_currency for call in calls if call.cost_currency is not None}
    return ResearchOutcome(
        model_decision=decision,
        human_correction=human_correction,
        accepted=accepted,
        latency_ms=sum(call.latency_ms for call in calls),
        inference_cost=sum(estimated_costs) if estimated_costs else None,
        cost_currency=next(iter(cost_currencies)) if len(cost_currencies) == 1 else None,
        providers=tuple(sorted({call.provider for call in calls})),
        model_ids=tuple(sorted({call.model_id for call in calls})),
        input_tokens=_sum_optional([call.token_usage.input_tokens for call in calls]),
        output_tokens=_sum_optional([call.token_usage.output_tokens for call in calls]),
        total_tokens=_sum_optional([call.token_usage.total_tokens for call in calls]),
    )


def build_product_intelligence_trace(
    result: AtomicIntelligenceResult,
    *,
    trace_id: str,
    occurred_at: datetime,
    human_correction: GoldComplianceLabel | None = None,
    accepted: bool | None = None,
) -> ResearchTrace:
    calls = result.model_calls
    decision = GoldComplianceLabel(result.proposed_decision.status.value)
    return ResearchTrace(
        trace_id=trace_id,
        case_id=result.original_requirement.requirement_id,
        occurred_at=occurred_at,
        state=_research_state(
            result,
            include_mapping=True,
            include_evidence=True,
            include_verifications=True,
        ),
        action=ResearchAction(
            action=ResearchActionType.SELECT_DECISION,
            selected_evidence_span_ids=(
                *result.proposed_decision.supporting_evidence_span_ids,
                *result.proposed_decision.contradicting_evidence_span_ids,
            ),
            selected_decision=decision,
            rationale="Deterministic guarded-compliance-v1 policy; human approval still required",
        ),
        outcome=_research_outcome(
            calls,
            decision=decision,
            human_correction=human_correction,
            accepted=accepted,
        ),
    )


def build_product_intelligence_traces(
    result: AtomicIntelligenceResult,
    *,
    trace_id_prefix: str,
    occurred_at: datetime,
    extraction_model_call: ModelCallRecord | None = None,
    human_correction: GoldComplianceLabel | None = None,
    accepted: bool | None = None,
) -> tuple[ResearchTrace, ...]:
    case_id = result.original_requirement.requirement_id
    empty_outcome = _research_outcome(())
    events: list[ResearchTrace] = [
        ResearchTrace(
            trace_id=f"{trace_id_prefix}:extract",
            case_id=case_id,
            occurred_at=occurred_at,
            state=_research_state(
                result,
                include_mapping=False,
                include_evidence=False,
                include_verifications=False,
            ),
            action=ResearchAction(action=ResearchActionType.EXTRACT),
            outcome=_research_outcome(
                (extraction_model_call,) if extraction_model_call is not None else ()
            ),
        ),
        ResearchTrace(
            trace_id=f"{trace_id_prefix}:map",
            case_id=case_id,
            occurred_at=occurred_at,
            state=_research_state(
                result,
                include_mapping=True,
                include_evidence=False,
                include_verifications=False,
            ),
            action=ResearchAction(action=ResearchActionType.MAP),
            outcome=empty_outcome,
        ),
    ]
    if result.retrieval_metadata is not None:
        for action in (ResearchActionType.RETRIEVE, ResearchActionType.RERANK):
            events.append(
                ResearchTrace(
                    trace_id=f"{trace_id_prefix}:{action.value.casefold()}",
                    case_id=case_id,
                    occurred_at=occurred_at,
                    state=_research_state(
                        result,
                        include_mapping=True,
                        include_evidence=True,
                        include_verifications=False,
                    ),
                    action=ResearchAction(
                        action=action,
                        selected_evidence_span_ids=tuple(
                            item.candidate.evidence_span_id
                            for item in result.candidate_evidence
                        ),
                    ),
                    outcome=empty_outcome,
                )
            )
    if result.verifications:
        events.append(
            ResearchTrace(
                trace_id=f"{trace_id_prefix}:verify",
                case_id=case_id,
                occurred_at=occurred_at,
                state=_research_state(
                    result,
                    include_mapping=True,
                    include_evidence=True,
                    include_verifications=True,
                ),
                action=ResearchAction(
                    action=ResearchActionType.VERIFY,
                    selected_evidence_span_ids=tuple(
                        item.evidence_span_id for item in result.verifications
                    ),
                ),
                outcome=_research_outcome(result.model_calls),
            )
        )
    decision = GoldComplianceLabel(result.proposed_decision.status.value)
    if result.proposed_decision.status in {
        GuardedComplianceStatus.UNKNOWN,
        GuardedComplianceStatus.NEEDS_CLARIFICATION,
    }:
        events.append(
            ResearchTrace(
                trace_id=f"{trace_id_prefix}:abstain",
                case_id=case_id,
                occurred_at=occurred_at,
                state=_research_state(
                    result,
                    include_mapping=True,
                    include_evidence=True,
                    include_verifications=True,
                ),
                action=ResearchAction(
                    action=ResearchActionType.ABSTAIN,
                    selected_decision=decision,
                ),
                outcome=_research_outcome(result.model_calls, decision=decision),
            )
        )
    else:
        events.append(
            build_product_intelligence_trace(
                result,
                trace_id=f"{trace_id_prefix}:select_decision",
                occurred_at=occurred_at,
            )
        )
    events.append(
        ResearchTrace(
            trace_id=f"{trace_id_prefix}:human_review",
            case_id=case_id,
            occurred_at=occurred_at,
            state=_research_state(
                result,
                include_mapping=True,
                include_evidence=True,
                include_verifications=True,
            ),
            action=ResearchAction(
                action=ResearchActionType.ESCALATE_HUMAN,
                selected_decision=decision,
                rationale="Human approval is mandatory; the pipeline never auto-approves",
            ),
            outcome=_research_outcome(
                (),
                decision=decision,
                human_correction=human_correction,
                accepted=accepted,
            ),
        )
    )
    return tuple(events)
