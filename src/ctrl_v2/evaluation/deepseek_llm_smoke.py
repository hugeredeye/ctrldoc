from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import date

from ctrl_v2.application.structured_contracts import PdfLocator, XlsxLocator
from ctrl_v2.domain.enums import EvidenceAuthorityLevel, EvidenceSourceType
from ctrl_v2.evaluation.deepseek_chat import (
    DEFAULT_MODEL,
    DeepSeekChatResearchAdapter,
    DeepSeekResearchConfig,
    DeepSeekResearchError,
)
from ctrl_v2.evaluation.intelligence_contracts import (
    AtomicRequirement,
    DataClassification,
    EvidenceVerificationRequest,
    GuardedComplianceStatus,
    MappingDisposition,
    MappingResult,
    ProductVersionCandidate,
    QuantitativeComparator,
    QuantitativeConstraint,
    RawRequirement,
    RequirementMappingCandidate,
    RequirementModality,
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


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Opt-in official DeepSeek public-safe smoke")
    parser.add_argument("--thinking", choices=("enabled", "disabled"), default="enabled")
    parser.add_argument(
        "--reasoning-effort", choices=("low", "high", "max"), default="high"
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--max-output-tokens", type=int, default=4096)
    parser.add_argument("--retries", type=int, default=1)
    return parser.parse_args()


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
    authorized = os.environ.get("CTRL_RUN_REAL_DEEPSEEK_SMOKE", "").casefold() == "true"
    key_present = bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
    if not authorized or not key_present:
        print(
            json.dumps(
                {
                    "api_actually_called": False,
                    "executed": False,
                    "model": DEFAULT_MODEL,
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

    config = DeepSeekResearchConfig(
        thinking_enabled=arguments.thinking == "enabled",
        reasoning_effort=arguments.reasoning_effort,
        timeout_seconds=arguments.timeout_seconds,
        max_output_tokens=arguments.max_output_tokens,
        max_retries=arguments.retries,
    )
    adapter = DeepSeekChatResearchAdapter(config)
    try:
        raw = _raw_extraction()
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
        metric_guarded, metric_decision, metric_record = _guarded_verification(
            adapter, metric_request
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
            metric_guarded.effective_output.label != VerificationLabel.ENTAILS
            and metric_decision.status != GuardedComplianceStatus.COMPLY
            and roadmap_guarded.effective_output.label != VerificationLabel.ENTAILS
            and roadmap_decision.status != GuardedComplianceStatus.COMPLY
        )
        report = {
            "api_actually_called": True,
            "executed": True,
            "model_requested": DEFAULT_MODEL,
            "models_reported": sorted({record.model_id for record in calls}),
            "thinking": arguments.thinking,
            "reasoning_effort": (
                arguments.reasoning_effort
                if arguments.thinking == "enabled"
                else "disabled"
            ),
            "safe_data_only": True,
            "structured_parse_success": True,
            "extraction": {
                "accepted_atomic_ids": [item.atomic_id for item in accepted],
                "conceptual_three_way_match": extraction_concept_match,
                "validation_issues": [
                    issue.code.value for issue in extraction_validation.issues
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
                "total": sum(record.token_usage.total_tokens or 0 for record in calls),
            },
            "latency_ms": sum(record.latency_ms for record in calls),
            "retries": sum(record.retry_count for record in calls),
            "overall_pass": extraction_concept_match and safety_pass,
            "quality_claim": "NONE_THREE_PUBLIC_SMOKE_CASES_ONLY",
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if not report["overall_pass"]:
            raise SystemExit(1)
    except DeepSeekResearchError as exc:
        print(
            json.dumps(
                {
                    "api_actually_called": True,
                    "executed": True,
                    "failure_reason": exc.failure_reason,
                    "latency_ms": exc.latency_ms,
                    "model": DEFAULT_MODEL,
                    "retries": exc.retry_count,
                    "safe_data_only": True,
                    "structured_parse_success": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
