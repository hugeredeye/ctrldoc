from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date
from enum import StrEnum

from ctrl_v2.application.structured_contracts import PdfLocator, XlsxLocator
from ctrl_v2.domain.enums import EvidenceAuthorityLevel, EvidenceSourceType
from ctrl_v2.evaluation.deepseek_chat import (
    DEFAULT_MODEL,
    DeepSeekChatResearchAdapter,
    DeepSeekResearchConfig,
    DeepSeekResearchError,
    SchemaValidationDiagnostics,
    canonical_payload_sha256,
)
from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicExtractionOutput,
    AtomicRequirement,
    DataClassification,
    EvidenceVerificationRequest,
    ExtractionValidationResult,
    GuardedComplianceStatus,
    MappingDisposition,
    MappingResult,
    ModelCallRecord,
    ProductVersionCandidate,
    QuantitativeComparator,
    QuantitativeConstraint,
    RawRequirement,
    RequirementMappingCandidate,
    RequirementModality,
    TokenUsage,
    VerificationLabel,
)
from ctrl_v2.evaluation.product_intelligence import (
    aggregate_evidence_conflicts,
    apply_evidence_guardrails,
    guarded_compliance_policy,
    validate_extraction,
)
from ctrl_v2.evaluation.retrieval_contracts import (
    EvidenceSpanCandidate,
    EvidenceSpanProvenance,
    RetrievedEvidenceSpan,
)

EXTRACTION_TEXT = (
    "Система должна поддерживать LDAP и SAML 2.0 и не менее "
    "10 000 одновременных пользователей."
)
FAST_MAX_OUTPUT_TOKENS = 4096
REASONING_MAX_OUTPUT_TOKENS = 8192


class DeepSeekSmokeMode(StrEnum):
    FAST = "FAST"
    REASONING = "REASONING"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Opt-in official DeepSeek public-safe smoke")
    parser.add_argument("--mode", choices=tuple(DeepSeekSmokeMode), required=True)
    parser.add_argument("--show-synthetic-output", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--retries", type=int, default=1)
    return parser.parse_args()


def _smoke_config(
    mode: DeepSeekSmokeMode,
    *,
    timeout_seconds: float,
    retries: int,
    show_synthetic_output: bool = False,
) -> DeepSeekResearchConfig:
    debug_classifications = (
        (DataClassification.SYNTHETIC_SAFE,) if show_synthetic_output else None
    )
    if mode is DeepSeekSmokeMode.FAST:
        options = {
            "allowed_data_classifications": debug_classifications
        } if debug_classifications is not None else {}
        return DeepSeekResearchConfig(
            experiment_mode=mode.value,
            thinking_enabled=False,
            reasoning_effort="high",
            temperature=0.0,
            timeout_seconds=timeout_seconds,
            max_output_tokens=FAST_MAX_OUTPUT_TOKENS,
            max_retries=retries,
            **options,
        )
    options = {
        "allowed_data_classifications": debug_classifications
    } if debug_classifications is not None else {}
    return DeepSeekResearchConfig(
        experiment_mode=mode.value,
        thinking_enabled=True,
        reasoning_effort="high",
        timeout_seconds=timeout_seconds,
        max_output_tokens=REASONING_MAX_OUTPUT_TOKENS,
        max_retries=retries,
        **options,
    )


def _token_report(usage: TokenUsage) -> dict[str, object]:
    return {
        "prompt_tokens": usage.input_tokens,
        "completion_tokens": usage.output_tokens,
        "completion_tokens_details": {
            "reasoning_tokens": usage.reasoning_tokens,
        },
        "total_tokens": usage.total_tokens,
    }


def _call_report(record: ModelCallRecord) -> dict[str, object]:
    return {
        "finish_reason": record.finish_reason,
        "model": record.model_id,
        **_token_report(record.token_usage),
        "latency_ms": record.latency_ms,
        "retries": record.retry_count,
    }


def _validation_report(
    diagnostics: SchemaValidationDiagnostics,
) -> dict[str, object]:
    return {
        "schema_model": diagnostics.schema_model,
        "validation_error_count": diagnostics.error_count,
        "validation_errors": [
            {
                "loc": list(issue.location),
                "path": issue.path,
                "type": issue.error_type,
                "message": issue.message,
            }
            for issue in diagnostics.errors
        ],
        "top_level_json_keys": list(diagnostics.top_level_json_keys),
        "canonical_output_sha256": diagnostics.canonical_output_sha256,
    }


def _synthetic_extraction_rejection_report(
    source: RawRequirement,
    output: AtomicExtractionOutput,
    validation: ExtractionValidationResult,
    *,
    allowed_input_sha256: frozenset[str],
) -> dict[str, object] | None:
    if (
        source.data_classification is not DataClassification.SYNTHETIC_SAFE
        or canonical_payload_sha256(source) not in allowed_input_sha256
        or not validation.rejected
    ):
        return None
    issues_by_atom = {
        atom.atomic_id: tuple(
            issue for issue in validation.issues if issue.atomic_id == atom.atomic_id
        )
        for atom in validation.rejected
    }
    return {
        "synthetic_output": output.model_dump(mode="json"),
        "rejected_atoms": [
            {
                "atomic_id": atom.atomic_id,
                "normalized_text": atom.normalized_text,
                "source_quote": atom.source_quote,
                "source_locator": atom.source_locator.model_dump(mode="json"),
                "source_start_offset": atom.source_start_offset,
                "source_end_offset": atom.source_end_offset,
                "quantitative_constraint": (
                    atom.quantitative_constraint.model_dump(mode="json")
                    if atom.quantitative_constraint is not None
                    else None
                ),
                "validation_issues": [
                    {
                        "code": issue.code.value,
                        "message": issue.message,
                        "blocking": issue.blocking,
                    }
                    for issue in issues_by_atom[atom.atomic_id]
                ],
            }
            for atom in validation.rejected
        ],
    }


def _raw_extraction() -> RawRequirement:
    return RawRequirement(
        requirement_id="deepseek-public-extraction-smoke",
        original_text=EXTRACTION_TEXT,
        source_context="Public synthetic identity and scale example",
        source_locator=XlsxLocator(sheet="PublicDemo", cell_range="A1"),
        data_classification=DataClassification.SYNTHETIC_SAFE,
    )


def _verification_request(
    *,
    case_id: str,
    requirement_text: str,
    evidence_text: str,
    source_type: EvidenceSourceType,
    capability_id: str,
    quantitative_constraint: QuantitativeConstraint | None = None,
) -> EvidenceVerificationRequest:
    atomic = AtomicRequirement(
        atomic_id=case_id,
        normalized_text=requirement_text,
        original_source_text=requirement_text,
        source_quote=requirement_text,
        source_start_offset=0,
        source_end_offset=len(requirement_text),
        source_locator=XlsxLocator(sheet="PublicDemo", cell_range="A2"),
        modality=RequirementModality.MUST,
        category="PUBLIC_DEMO",
        quantitative_constraint=quantitative_constraint,
    )
    mapping = RequirementMappingCandidate(
        requirement_id=case_id,
        disposition=MappingDisposition.MATCH,
        product_id="public-demo-product",
        product_version_id="public-demo-product-7",
        capability_id=capability_id,
        score=1.0,
        explanation="Hard-coded controlled public smoke mapping",
    )
    evidence_sha = hashlib.sha256(evidence_text.encode("utf-8")).hexdigest()
    evidence = RetrievedEvidenceSpan(
        candidate=EvidenceSpanCandidate(
            evidence_span_id=f"SPAN-{case_id}",
            canonical_text=evidence_text,
            provenance=EvidenceSpanProvenance(
                asset_path=f"public-smoke/{case_id}.pdf",
                document_key="public-demo-product-spec",
                document_version="public-demo-2026.1",
                source_sha256=evidence_sha,
                locator=PdfLocator(page=1),
                source_type=source_type,
                authority_level=EvidenceAuthorityLevel.AUTHORITATIVE,
                valid_from=date(2026, 1, 1),
                product_version_key="public-demo-product-7",
            ),
        ),
        rank=1,
        score=1.0,
        method="hard-coded-public-smoke",
    )
    return EvidenceVerificationRequest(
        requirement=atomic,
        mapping=mapping,
        evidence=evidence,
        product_version=ProductVersionCandidate(
            product_version_id="public-demo-product-7",
            product_id="public-demo-product",
            version_label="7.0",
            valid_from=date(2026, 1, 1),
        ),
        assessment_as_of=date(2026, 8, 21),
        data_classification=DataClassification.SYNTHETIC_SAFE,
    )


def _guarded_verification(adapter, request):
    provider_output, record = adapter.verify(request)
    guarded = apply_evidence_guardrails(request, provider_output, record)
    mapping = MappingResult(
        candidates=(request.mapping,),
        selected=request.mapping,
        requires_human_review=False,
    )
    conflict = aggregate_evidence_conflicts((request.evidence,), (guarded,))
    decision = guarded_compliance_policy(
        request.requirement,
        mapping,
        (guarded,),
        conflict,
    )
    return guarded, decision, record


def _normalized_number(text: str) -> str:
    return re.sub(r"\D", "", text)


def main() -> None:
    arguments = _arguments()
    mode = DeepSeekSmokeMode(arguments.mode)
    config = _smoke_config(
        mode,
        timeout_seconds=arguments.timeout_seconds,
        retries=arguments.retries,
        show_synthetic_output=arguments.show_synthetic_output,
    )
    authorized = os.environ.get("CTRL_RUN_REAL_DEEPSEEK_SMOKE", "").casefold() == "true"
    key_present = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
    if not authorized or not key_present:
        print(
            json.dumps(
                {
                    "api_actually_called": False,
                    "executed": False,
                    "model": DEFAULT_MODEL,
                    "mode": mode.value,
                    "max_output_tokens": config.max_output_tokens,
                    "temperature": config.temperature,
                    "thinking": "enabled" if config.thinking_enabled else "disabled",
                    "reasoning_effort": (
                        config.reasoning_effort
                        if config.thinking_enabled
                        else "disabled"
                    ),
                    "reason": (
                        "CTRL_RUN_REAL_DEEPSEEK_SMOKE=true and DEEPSEEK_API_KEY are required"
                    ),
                    "safe_data_only": True,
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(2)

    raw = _raw_extraction()
    metric_request = _verification_request(
        case_id="REQ-CONCURRENT",
        requirement_text="The product must support at least 10,000 concurrent users.",
        evidence_text="The product supports 10,000 registered users.",
        source_type=EvidenceSourceType.OFFICIAL_SPECIFICATION,
        capability_id="scale.concurrent-users",
        quantitative_constraint=QuantitativeConstraint(
            comparator=QuantitativeComparator.GREATER_THAN_OR_EQUAL,
            value="10,000",
            unit="concurrent users",
        ),
    )
    roadmap_request = _verification_request(
        case_id="REQ-FUTURE-CAPABILITY",
        requirement_text="The product must support the future public demo capability.",
        evidence_text=(
            "The future public demo capability is planned on the product roadmap."
        ),
        source_type=EvidenceSourceType.ROADMAP,
        capability_id="future.public-demo",
    )
    builtin_inputs = (raw, metric_request, roadmap_request)
    debug_hashes = (
        frozenset(canonical_payload_sha256(payload) for payload in builtin_inputs)
        if arguments.show_synthetic_output
        else frozenset()
    )
    adapter = DeepSeekChatResearchAdapter(
        config,
        synthetic_schema_debug_input_sha256=debug_hashes,
    )
    try:
        extraction_result = adapter.extract(raw)
        extraction_validation = validate_extraction(
            raw, extraction_result.output.requirements
        )
        accepted = extraction_validation.accepted
        accepted_text = " ".join(item.normalized_text.casefold() for item in accepted)
        numeric_atoms = [
            item
            for item in accepted
            if item.quantitative_constraint is not None
            and item.quantitative_constraint.comparator
            == QuantitativeComparator.GREATER_THAN_OR_EQUAL
            and _normalized_number(item.quantitative_constraint.value) == "10000"
        ]
        extraction_concept_match = (
            len(accepted) == 3
            and not extraction_validation.rejected
            and "ldap" in accepted_text
            and "saml 2.0" in accepted_text
            and bool(numeric_atoms)
        )
        extraction_debug = _synthetic_extraction_rejection_report(
            raw,
            extraction_result.output,
            extraction_validation,
            allowed_input_sha256=debug_hashes,
        )

        metric_guarded, metric_decision, metric_record = _guarded_verification(
            adapter, metric_request
        )

        roadmap_guarded, roadmap_decision, roadmap_record = _guarded_verification(
            adapter, roadmap_request
        )
        records = (
            extraction_result.model_call,
            metric_record,
            roadmap_record,
        )
        calls = tuple(record for record in records if record is not None)
        safety_pass = (
            metric_guarded.effective_output.label == VerificationLabel.INSUFFICIENT
            and metric_decision.status == GuardedComplianceStatus.UNKNOWN
            and roadmap_guarded.effective_output.label != VerificationLabel.ENTAILS
            and roadmap_decision.status != GuardedComplianceStatus.COMPLY
        )
        report = {
            "api_actually_called": True,
            "executed": True,
            "model_requested": DEFAULT_MODEL,
            "models_reported": sorted({record.model_id for record in calls}),
            "mode": mode.value,
            "max_output_tokens": config.max_output_tokens,
            "temperature": config.temperature,
            "thinking": "enabled" if config.thinking_enabled else "disabled",
            "reasoning_effort": (
                config.reasoning_effort if config.thinking_enabled else "disabled"
            ),
            "safe_data_only": True,
            "structured_parse_success": True,
            "extraction": {
                "accepted_atomic_ids": [item.atomic_id for item in accepted],
                "conceptual_three_way_match": extraction_concept_match,
                "validation_issues": [
                    issue.code.value for issue in extraction_validation.issues
                ],
                "source_anchor_resolutions": [
                    resolution.model_dump(mode="json")
                    for resolution in extraction_validation.source_anchor_resolutions
                ],
            },
            "registered_vs_concurrent": {
                "provider_label": metric_guarded.provider_output.label.value,
                "effective_label": metric_guarded.effective_output.label.value,
                "decision": metric_decision.status.value,
                "guardrails_altered": (
                    metric_guarded.provider_output.label
                    != metric_guarded.effective_output.label
                    or bool(metric_guarded.guardrail_adjustments)
                ),
            },
            "roadmap": {
                "provider_label": roadmap_guarded.provider_output.label.value,
                "effective_label": roadmap_guarded.effective_output.label.value,
                "decision": roadmap_decision.status.value,
                "guardrails_altered": (
                    roadmap_guarded.provider_output.label
                    != roadmap_guarded.effective_output.label
                    or bool(roadmap_guarded.guardrail_adjustments)
                ),
            },
            "tokens": {
                "input": sum(record.token_usage.input_tokens or 0 for record in calls),
                "output": sum(record.token_usage.output_tokens or 0 for record in calls),
                "reasoning": sum(
                    record.token_usage.reasoning_tokens or 0 for record in calls
                ),
                "total": sum(record.token_usage.total_tokens or 0 for record in calls),
            },
            "provider_calls": [_call_report(record) for record in calls],
            "latency_ms": sum(record.latency_ms for record in calls),
            "retries": sum(record.retry_count for record in calls),
            "overall_pass": extraction_concept_match and safety_pass,
            "quality_claim": "NONE_THREE_PUBLIC_SMOKE_CASES_ONLY",
        }
        if extraction_debug is not None:
            report["extraction"].update(extraction_debug)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if not report["overall_pass"]:
            raise SystemExit(1)
    except DeepSeekResearchError as exc:
        report = {
                    "api_actually_called": True,
                    "executed": True,
                    "failure_reason": exc.failure_reason,
                    "finish_reason": exc.finish_reason,
                    "latency_ms": exc.latency_ms,
                    "max_output_tokens": config.max_output_tokens,
                    "temperature": config.temperature,
                    "mode": mode.value,
                    "model_requested": DEFAULT_MODEL,
                    "model_reported": exc.response_model,
                    "thinking": "enabled" if config.thinking_enabled else "disabled",
                    "reasoning_effort": (
                        config.reasoning_effort
                        if config.thinking_enabled
                        else "disabled"
                    ),
                    "retries": exc.retry_count,
                    "safe_data_only": True,
                    "structured_parse_success": False,
                    **_token_report(exc.token_usage),
                }
        if exc.validation_diagnostics is not None:
            report["schema_validation"] = _validation_report(
                exc.validation_diagnostics
            )
        if arguments.show_synthetic_output and exc.synthetic_output is not None:
            report["synthetic_output"] = exc.synthetic_output
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
