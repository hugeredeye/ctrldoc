from __future__ import annotations

import json
from pathlib import Path

from ctrl_v2.evaluation.authoring import (
    add_manual_case,
    initialize_dataset,
    validate_case,
    validate_dataset,
)
from ctrl_v2.evaluation.contracts import (
    ConflictCase,
    DecisionCase,
    EvaluationFixture,
    EvaluationVersions,
    ExtractionCase,
    RetrievalCase,
)
from ctrl_v2.evaluation.metrics import evaluate


def _manual_case() -> dict[str, object]:
    source_text = "The platform shall support SAML SSO."
    return {
        "case_id": "sso-001",
        "description": "Human-reviewed SAML requirement",
        "annotation": {
            "annotator": "reviewer-1",
            "annotation_version": "1.0",
            "annotated_at": "2026-08-19T00:00:00Z",
        },
        "provenance": {
            "source_collection": "manual-test",
            "source_revision": "1",
        },
        "source_requirement": {
            "asset_path": "assets/rfp.xlsx",
            "source_text": source_text,
            "locator": {"kind": "XLSX", "sheet": "Requirements", "cell_range": "A1"},
        },
        "gold_atomic_requirements": [
            {
                "key": "REQ-1",
                "atomic_text": source_text,
                "source_quote": source_text,
                "source_start_offset": 0,
                "source_end_offset": len(source_text),
                "modality": "MUST",
            }
        ],
        "gold_mappings": [
            {
                "atomic_requirement_key": "REQ-1",
                "product_key": "ctrl",
                "product_version_key": "ctrl-7",
                "capability_key": "security.sso.saml",
            }
        ],
        "gold_evidence_spans": [
            {
                "key": "SPAN-1",
                "atomic_requirement_key": "REQ-1",
                "product_version_key": "ctrl-7",
                "asset_path": "assets/spec.pdf",
                "document_key": "ctrl-spec",
                "document_version": "7",
                "source_type": "OFFICIAL_SPECIFICATION",
                "authority_level": "AUTHORITATIVE",
                "valid_from": "2026-01-01",
                "exact_quote": "SAML 2.0 is supported.",
                "locator": {"kind": "PDF", "page": 3},
            }
        ],
        "gold_compliance_outcomes": [
            {
                "atomic_requirement_key": "REQ-1",
                "product_version_key": "ctrl-7",
                "assessment_as_of": "2026-08-17",
                "outcome": "COMPLY",
                "critical": True,
            }
        ],
    }


def test_manual_gold_dataset_authoring_round_trip(tmp_path: Path):
    dataset_path = tmp_path / "dataset.json"
    case_path = tmp_path / "reviewed-case.json"
    initialize_dataset(dataset_path, "product-rfp-gold", "1.0.0", "Human curated")
    case_path.write_text(json.dumps(_manual_case()), encoding="utf-8")

    case_id, case_digest = validate_case(case_path)
    add_manual_case(dataset_path, case_path)
    case_count, digest = validate_dataset(dataset_path)

    assert case_id == "sso-001"
    assert len(case_digest) == 64
    assert case_count == 1
    assert len(digest) == 64


def test_metrics_accept_predictions_derived_from_gold_cases():
    versions = EvaluationVersions(
        dataset="product-rfp-gold/1.0.0",
        parser="parser-v1",
        extraction_contract="1.0",
        extraction_prompt="manual-baseline",
        model="manual-baseline",
        retrieval="manual-baseline",
        decision_prompt="manual-baseline",
        conflict_prompt="manual-baseline",
    )
    fixture = EvaluationFixture(
        versions=versions,
        extraction=[
            ExtractionCase(
                case_id="sso-001",
                expected_requirement_keys={"REQ-1"},
                predicted_requirement_keys={"REQ-1"},
            )
        ],
        retrieval=[
            RetrievalCase(
                case_id="sso-001",
                expected_evidence_span_ids={"SPAN-1"},
                ranked_evidence_span_ids=["SPAN-1"],
                k=5,
            )
        ],
        decisions=[
            DecisionCase(
                case_id="sso-001",
                expected="COMPLY",
                predicted="COMPLY",
                human_approved_without_edit=True,
            )
        ],
        conflicts=[
            ConflictCase(
                case_id="sso-001",
                is_critical=False,
                expected_conflict=False,
                predicted_conflict=False,
                decision="COMPLY",
            )
        ],
    )

    assert evaluate(fixture).as_dict() == {
        "atomic_requirement_recall": 1.0,
        "evidence_recall_at_k": 1.0,
        "compliance_accuracy": 1.0,
        "critical_false_comply_rate": 0.0,
        "unedited_human_approval_rate": 1.0,
    }
