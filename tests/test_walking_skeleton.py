from __future__ import annotations

import hashlib
import logging

from tests.helpers import Journey


def approve(journey: Journey, decision_id: str):
    return journey.post(
        f"/compliance-decisions/{decision_id}/approve",
        json={"reviewer_subject": "reviewer@example.test", "comment": "Verified"},
    )


def test_complete_walking_skeleton_and_reproducible_xlsx(client):
    journey = Journey(client)
    state = journey.build_until_decision()
    assert state["decision"]["risk"] == "LOW"

    approval = approve(journey, state["decision"]["id"])
    assert approval.status_code == 200, approval.text
    assert approval.json()["status"] == "APPROVED"

    response = journey.post(
        "/responses",
        json={"rfp_id": state["rfp"]["id"], "decision_ids": [state["decision"]["id"]]},
    )
    assert response.status_code == 201, response.text
    snapshot = response.json()
    assert (
        snapshot["items"][0]["evidence"][0]["document_version_id"]
        == state["product_document"]["document_version_id"]
    )

    first_export = journey.post(f"/responses/{snapshot['id']}/export-xlsx")
    second_export = journey.post(f"/responses/{snapshot['id']}/export-xlsx")
    assert first_export.status_code == second_export.status_code == 200
    assert first_export.json()["sha256"] == second_export.json()["sha256"]

    first_download = client.get(
        f"/api/v1/workspaces/{journey.workspace_id}/exports/{first_export.json()['id']}/content",
        headers=journey.headers,
    )
    second_download = client.get(
        f"/api/v1/workspaces/{journey.workspace_id}/exports/{second_export.json()['id']}/content",
        headers=journey.headers,
    )
    assert first_download.content == second_download.content
    assert hashlib.sha256(first_download.content).hexdigest() == first_export.json()["sha256"]


def test_approved_comply_without_evidence_span_is_impossible(client):
    journey = Journey(client)
    state = journey.build_until_decision(with_evidence=False)

    approval = approve(journey, state["decision"]["id"])

    assert approval.status_code == 409
    assert "EvidenceSpan" in approval.json()["detail"]


def test_low_risk_decision_supports_batch_final_approval(client):
    journey = Journey(client)
    state = journey.build_until_decision()

    approval = journey.post(
        "/compliance-decisions/batch-approve",
        json={
            "decision_ids": [state["decision"]["id"]],
            "reviewer_subject": "batch-reviewer@example.test",
            "comment": "Strong non-conflicting evidence",
        },
    )

    assert approval.status_code == 200, approval.text
    assert approval.json()[0]["status"] == "APPROVED"


def test_cross_workspace_access_is_impossible(client):
    first = Journey(client, "First")
    second = Journey(client, "Second")
    document = second.upload("Second workspace only", "RFP", "private.xlsx")

    response = client.get(
        f"/api/v1/workspaces/{second.workspace_id}/document-versions/"
        f"{document['document_version_id']}/content",
        headers=first.headers,
    )

    assert response.status_code == 404
    assert b"Second workspace only" not in response.content


def test_evidence_span_cannot_mix_document_versions(client):
    journey = Journey(client)
    state = journey.build_until_decision()
    other = journey.upload("A different immutable version", "PRODUCT_KNOWLEDGE", "other.xlsx")
    linked = journey.post(
        f"/product-versions/{state['product_version']['id']}/documents",
        json={"document_version_id": other["document_version_id"], "source_type": "OTHER"},
    )
    assert linked.status_code == 201, linked.text
    original_block = state["product_document"]["blocks"][0]

    response = journey.post(
        "/evidence-spans",
        json={
            "requirement_id": state["requirement"]["id"],
            "product_version_id": state["product_version"]["id"],
            "summary": "Invalid mixed provenance",
            "source_type": "OTHER",
            "authority_level": "UNVERIFIED",
            "valid_from": "2026-01-01",
            "document_version_id": other["document_version_id"],
            "document_block_id": original_block["id"],
            "start_offset": 0,
            "end_offset": len(original_block["text"]),
        },
    )

    assert response.status_code == 409
    assert "exact DocumentVersion" in response.json()["detail"]


def test_approved_decision_is_immutable(client):
    journey = Journey(client)
    state = journey.build_until_decision()
    assert approve(journey, state["decision"]["id"]).status_code == 200

    changed = client.patch(
        f"/api/v1/workspaces/{journey.workspace_id}/compliance-decisions/"
        f"{state['decision']['id']}",
        headers=journey.headers,
        json={"rationale": "Change an approved conclusion"},
    )

    assert changed.status_code == 409
    assert "immutable" in changed.json()["detail"]


def test_document_content_and_workspace_secret_are_not_logged(client, caplog):
    caplog.set_level(logging.INFO)
    journey = Journey(client)
    marker = "CONFIDENTIAL-DOCUMENT-MARKER-74815"

    journey.upload(marker, "RFP", "confidential.xlsx")

    rendered_logs = caplog.text
    assert marker not in rendered_logs
    assert journey.workspace["access_token"] not in rendered_logs
