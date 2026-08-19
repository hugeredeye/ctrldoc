from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from ctrl_v2.infrastructure.persistence.database import Database, DatabaseReadinessError
from tests.helpers import Journey

pytestmark = pytest.mark.postgres


def _set_workspace(connection, workspace_id: str) -> None:
    connection.execute(
        text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
        {"workspace_id": workspace_id},
    )


def _approve_and_snapshot(journey: Journey, state: dict) -> dict:
    approval = journey.post(
        f"/compliance-decisions/{state['decision']['id']}/approve",
        json={"comment": "Provenance boundary approval"},
    )
    assert approval.status_code == 200, approval.text
    response = journey.post(
        "/responses",
        json={
            "rfp_id": state["rfp"]["id"],
            "decision_ids": [state["decision"]["id"]],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _document_metadata(database_url: str, version_id: str):
    engine = create_engine(database_url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT object_key, sha256, size_bytes FROM document_versions "
                    "WHERE id = :version_id"
                ),
                {"version_id": version_id},
            ).one()
    finally:
        engine.dispose()


@pytest.mark.parametrize("tamper_mode", ["replace", "truncate"])
def test_document_download_fails_closed_after_object_tamper(
    client, postgres_urls, tamper_mode
):
    journey = Journey(client, f"Object tamper {tamper_mode}")
    document = journey.upload("Immutable customer source", "RFP", "source.xlsx")
    metadata = _document_metadata(postgres_urls.admin, document["document_version_id"])
    object_path = client.app.state.workflow.storage.root / metadata.object_key

    if tamper_mode == "replace":
        object_path.write_bytes(b"attacker-controlled replacement")
    else:
        with object_path.open("r+b") as output:
            output.truncate(max(1, metadata.size_bytes // 2))

    response = client.get(
        f"/api/v1/workspaces/{journey.workspace_id}/document-versions/"
        f"{document['document_version_id']}/content",
        headers=journey.headers,
    )

    assert response.status_code == 409
    assert response.json()["type"] == "object-integrity-error"
    assert "attacker-controlled" not in response.text


def test_changed_database_object_identity_is_not_trusted(client, postgres_urls):
    journey = Journey(client, "DB object identity tamper")
    document = journey.upload("Original trusted source", "RFP", "source.xlsx")
    version_id = document["document_version_id"]
    original = _document_metadata(postgres_urls.admin, version_id)
    forged_sha256 = "0" * 64
    forged_key = original.object_key.replace(original.sha256, forged_sha256)
    engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE document_versions DISABLE TRIGGER document_versions_immutable")
            )
            connection.execute(
                text(
                    "UPDATE document_versions SET sha256 = :sha256, object_key = :object_key "
                    "WHERE id = :version_id"
                ),
                {
                    "sha256": forged_sha256,
                    "object_key": forged_key,
                    "version_id": version_id,
                },
            )
            connection.execute(
                text("ALTER TABLE document_versions ENABLE TRIGGER document_versions_immutable")
            )

        response = client.get(
            f"/api/v1/workspaces/{journey.workspace_id}/document-versions/"
            f"{version_id}/content",
            headers=journey.headers,
        )
        assert response.status_code == 409
        assert response.json()["type"] == "object-integrity-error"
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE document_versions DISABLE TRIGGER document_versions_immutable")
            )
            connection.execute(
                text(
                    "UPDATE document_versions SET sha256 = :sha256, object_key = :object_key "
                    "WHERE id = :version_id"
                ),
                {
                    "sha256": original.sha256,
                    "object_key": original.object_key,
                    "version_id": version_id,
                },
            )
            connection.execute(
                text("ALTER TABLE document_versions ENABLE TRIGGER document_versions_immutable")
            )
        engine.dispose()


def test_evidence_correction_is_append_only_and_actor_attributed(client, postgres_urls):
    journey = Journey(client, "Evidence correction")
    state = journey.build_until_decision()
    prior = state["evidence"]
    block = state["product_document"]["blocks"][0]

    correction = journey.post(
        "/evidence-spans",
        json={
            "requirement_id": state["requirement"]["id"],
            "product_version_id": state["product_version"]["id"],
            "summary": "Corrected evidence without rewriting history.",
            "source_type": "OFFICIAL_SPECIFICATION",
            "authority_level": "AUTHORITATIVE",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
            "document_version_id": state["product_document"]["document_version_id"],
            "document_block_id": block["id"],
            "start_offset": 0,
            "end_offset": len(block["text"]),
            "supersedes_evidence_id": prior["evidence_id"],
        },
    )

    assert correction.status_code == 201, correction.text
    principal = client.get("/api/v1/me", headers=journey.headers).json()
    assert correction.json()["supersedes_evidence_id"] == prior["evidence_id"]
    assert correction.json()["created_by_principal_id"] == principal["id"]
    engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT id, summary, supersedes_id, created_by_principal_id "
                    "FROM evidence WHERE id IN (:prior_id, :correction_id) ORDER BY id"
                ),
                {
                    "prior_id": prior["evidence_id"],
                    "correction_id": correction.json()["evidence_id"],
                },
            ).mappings()
            by_id = {row["id"]: row for row in rows}
    finally:
        engine.dispose()
    assert by_id[prior["evidence_id"]]["supersedes_id"] is None
    assert by_id[correction.json()["evidence_id"]]["supersedes_id"] == prior["evidence_id"]


def test_new_evidence_without_authenticated_actor_is_denied(client, postgres_urls):
    journey = Journey(client, "Evidence actor trigger")
    state = journey.build_until_decision()
    engine = create_engine(postgres_urls.runtime, hide_parameters=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            _set_workspace(connection, journey.workspace_id)
            with pytest.raises(DBAPIError, match="requires an authenticated Principal"):
                connection.execute(
                    text(
                        "INSERT INTO evidence "
                        "(workspace_id, id, requirement_id, product_version_id, summary, "
                        "source_type, authority_level, valid_from, valid_to, status, "
                        "retrieval_rank, supersedes_id, created_by_principal_id, created_at) "
                        "SELECT workspace_id, :new_id, requirement_id, product_version_id, "
                        "'unattributed', source_type, authority_level, valid_from, valid_to, "
                        "status, NULL, NULL, NULL, now() FROM evidence "
                        "WHERE id = :evidence_id"
                    ),
                    {"new_id": str(uuid4()), "evidence_id": state["evidence"]["evidence_id"]},
                )
            transaction.rollback()
    finally:
        engine.dispose()


def test_runtime_cannot_execute_provenance_trigger_functions(postgres_urls):
    engine = create_engine(postgres_urls.runtime, hide_parameters=True)
    try:
        with engine.connect() as connection:
            with pytest.raises(DBAPIError, match="permission denied"):
                connection.execute(text("SELECT ctrl_require_evidence_actor()"))
    finally:
        engine.dispose()


def test_readiness_rejects_executable_boundary_function(postgres_urls):
    admin_engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "GRANT EXECUTE ON FUNCTION ctrl_require_evidence_actor() "
                    "TO ctrl_v2_runtime"
                )
            )
        database = Database(postgres_urls.runtime)
        try:
            with pytest.raises(DatabaseReadinessError, match="functions executable"):
                database.verify_runtime_readiness()
        finally:
            database.engine.dispose()
    finally:
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "REVOKE ALL PRIVILEGES ON FUNCTION ctrl_require_evidence_actor() "
                    "FROM ctrl_v2_runtime"
                )
            )
        admin_engine.dispose()


def test_provenance_chain_is_complete_and_deterministic(client, postgres_urls):
    journey = Journey(client, "Complete provenance chain")
    state = journey.build_until_decision()
    response = _approve_and_snapshot(journey, state)
    snapshot_evidence = response["items"][0]["evidence"][0]
    engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with engine.connect() as connection:
            chain = connection.execute(
                text(
                    """
                    SELECT items.id AS response_item_id,
                           decisions.id AS decision_id,
                           spans.id AS evidence_span_id,
                           evidence_rows.id AS evidence_id,
                           blocks.id AS block_id,
                           representations.id AS representation_id,
                           versions.id AS document_version_id,
                           versions.object_key,
                           versions.sha256,
                           versions.size_bytes
                    FROM response_items items
                    JOIN compliance_decisions decisions
                      ON decisions.workspace_id = items.workspace_id
                     AND decisions.id = items.decision_id
                    JOIN decision_evidence_spans links
                      ON links.workspace_id = decisions.workspace_id
                     AND links.decision_id = decisions.id
                    JOIN evidence_spans spans
                      ON spans.workspace_id = links.workspace_id
                     AND spans.id = links.evidence_span_id
                    JOIN evidence evidence_rows
                      ON evidence_rows.workspace_id = spans.workspace_id
                     AND evidence_rows.id = spans.evidence_id
                    JOIN document_blocks blocks
                      ON blocks.workspace_id = spans.workspace_id
                     AND blocks.id = spans.document_block_id
                    JOIN document_representations representations
                      ON representations.workspace_id = spans.workspace_id
                     AND representations.id = spans.representation_id
                    JOIN document_versions versions
                      ON versions.workspace_id = spans.workspace_id
                     AND versions.id = spans.document_version_id
                    WHERE items.workspace_id = :workspace_id
                      AND items.response_id = :response_id
                    """
                ),
                {"workspace_id": journey.workspace_id, "response_id": response["id"]},
            ).mappings().one()
    finally:
        engine.dispose()

    assert chain["decision_id"] == state["decision"]["id"]
    assert chain["evidence_span_id"] == state["evidence"]["evidence_span_id"]
    assert chain["evidence_id"] == state["evidence"]["evidence_id"]
    assert chain["document_version_id"] == state["product_document"]["document_version_id"]
    assert chain["sha256"] in chain["object_key"]
    assert chain["size_bytes"] > 0
    assert snapshot_evidence["evidence_id"] == chain["evidence_id"]
    assert snapshot_evidence["document_object_key"] == chain["object_key"]
    assert snapshot_evidence["document_sha256"] == chain["sha256"]
    assert snapshot_evidence["document_size_bytes"] == chain["size_bytes"]


def test_provenance_and_historical_rows_cannot_be_mutated_or_deleted(
    client, postgres_urls
):
    journey = Journey(client, "Immutable provenance graph")
    state = journey.build_until_decision()
    response = _approve_and_snapshot(journey, state)
    export = journey.post(f"/responses/{response['id']}/export-xlsx")
    assert export.status_code == 200, export.text
    engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with engine.connect() as connection:
            ids = connection.execute(
                text(
                    """
                    SELECT
                      (SELECT id FROM human_reviews WHERE decision_id = :decision_id) review_id,
                      (SELECT id FROM response_items WHERE response_id = :response_id) item_id
                    """
                ),
                {"decision_id": state["decision"]["id"], "response_id": response["id"]},
            ).one()
    finally:
        engine.dispose()

    mutations = [
        (
            "DELETE FROM document_versions WHERE workspace_id=:workspace_id AND id=:entity_id",
            state["product_document"]["document_version_id"],
            "DocumentVersion is immutable",
        ),
        (
            "UPDATE evidence_spans SET exact_quote='tampered' "
            "WHERE workspace_id=:workspace_id AND id=:entity_id",
            state["evidence"]["evidence_span_id"],
            "EvidenceSpan referenced by a decision is immutable",
        ),
        (
            "DELETE FROM evidence_spans WHERE workspace_id=:workspace_id AND id=:entity_id",
            state["evidence"]["evidence_span_id"],
            "EvidenceSpan referenced by a decision is immutable",
        ),
        (
            "UPDATE evidence SET summary='tampered' "
            "WHERE workspace_id=:workspace_id AND id=:entity_id",
            state["evidence"]["evidence_id"],
            "Evidence referenced by a decision is immutable",
        ),
        (
            "DELETE FROM evidence WHERE workspace_id=:workspace_id AND id=:entity_id",
            state["evidence"]["evidence_id"],
            "Evidence referenced by a decision is immutable",
        ),
        (
            "UPDATE document_representations SET content_hash=:replacement "
            "WHERE workspace_id=:workspace_id AND id=:entity_id",
            state["product_document"]["representation_id"],
            "DocumentRepresentation used by Evidence is immutable",
        ),
        (
            "UPDATE document_blocks SET text='tampered' "
            "WHERE workspace_id=:workspace_id AND id=:entity_id",
            state["product_document"]["blocks"][0]["id"],
            "DocumentBlock used by Evidence is immutable",
        ),
        (
            "UPDATE human_reviews SET comment='tampered' "
            "WHERE workspace_id=:workspace_id AND id=:entity_id",
            ids.review_id,
            "human_reviews is append-only",
        ),
        (
            "DELETE FROM human_reviews WHERE workspace_id=:workspace_id AND id=:entity_id",
            ids.review_id,
            "human_reviews is append-only",
        ),
        (
            "DELETE FROM responses WHERE workspace_id=:workspace_id AND id=:entity_id",
            response["id"],
            "responses is append-only",
        ),
        (
            "UPDATE response_items SET item_json='{}'::json "
            "WHERE workspace_id=:workspace_id AND id=:entity_id",
            ids.item_id,
            "response_items is append-only",
        ),
        (
            "DELETE FROM response_items WHERE workspace_id=:workspace_id AND id=:entity_id",
            ids.item_id,
            "response_items is append-only",
        ),
        (
            "UPDATE response_exports SET format='PDF' "
            "WHERE workspace_id=:workspace_id AND id=:entity_id",
            export.json()["id"],
            "response_exports is append-only",
        ),
    ]
    engine = create_engine(postgres_urls.runtime, hide_parameters=True)
    try:
        for statement, entity_id, message in mutations:
            with engine.connect() as connection:
                transaction = connection.begin()
                _set_workspace(connection, journey.workspace_id)
                with pytest.raises(DBAPIError, match=message):
                    connection.execute(
                        text(statement),
                        {
                            "workspace_id": journey.workspace_id,
                            "entity_id": entity_id,
                            "replacement": "0" * 64,
                        },
                    )
                transaction.rollback()
    finally:
        engine.dispose()


def test_response_item_rejects_unapproved_decision(client, postgres_urls):
    journey = Journey(client, "Response item provenance constraint")
    state = journey.build_until_decision(with_evidence=False)
    engine = create_engine(postgres_urls.runtime, hide_parameters=True)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        _set_workspace(connection, journey.workspace_id)
        response_id = str(uuid4())
        connection.execute(
            text(
                "INSERT INTO responses "
                "(workspace_id,id,rfp_id,version_no,assessment_as_of,status,snapshot_hash,"
                "snapshot_json,created_at) VALUES "
                "(:workspace_id,:response_id,:rfp_id,9999,'2026-08-17','SNAPSHOT',:hash,"
                "'{}'::json,now())"
            ),
            {
                "workspace_id": journey.workspace_id,
                "response_id": response_id,
                "rfp_id": state["rfp"]["id"],
                "hash": "0" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO response_items "
                "(workspace_id,id,response_id,requirement_id,decision_id,source_order,item_json,"
                "created_at) VALUES "
                "(:workspace_id,:item_id,:response_id,:requirement_id,:decision_id,1,"
                "'{}'::json,now())"
            ),
            {
                "workspace_id": journey.workspace_id,
                "item_id": str(uuid4()),
                "response_id": response_id,
                "requirement_id": state["requirement"]["id"],
                "decision_id": state["decision"]["id"],
            },
        )
        with pytest.raises(DBAPIError, match="requires an approved ComplianceDecision"):
            transaction.commit()
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()


def test_cross_workspace_evidence_supersession_is_denied(client):
    first = Journey(client, "Evidence tenant one")
    first_state = first.build_until_decision()
    second = Journey(client, "Evidence tenant two")
    second_state = second.build_until_decision()
    block = first_state["product_document"]["blocks"][0]

    response = first.post(
        "/evidence-spans",
        json={
            "requirement_id": first_state["requirement"]["id"],
            "product_version_id": first_state["product_version"]["id"],
            "summary": "Cross-tenant supersession attempt",
            "source_type": "OFFICIAL_SPECIFICATION",
            "authority_level": "AUTHORITATIVE",
            "valid_from": "2026-01-01",
            "valid_to": "2026-12-31",
            "document_version_id": first_state["product_document"]["document_version_id"],
            "document_block_id": block["id"],
            "start_offset": 0,
            "end_offset": len(block["text"]),
            "supersedes_evidence_id": second_state["evidence"]["evidence_id"],
        },
    )

    assert response.status_code == 404
    assert "Superseded Evidence" in response.json()["detail"]
