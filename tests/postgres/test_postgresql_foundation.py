from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import DBAPIError

from ctrl_v2.infrastructure.persistence import Database, SqlAlchemyUnitOfWorkFactory
from tests.helpers import Journey

pytestmark = pytest.mark.postgres


def _set_workspace(connection: Any, workspace_id: str) -> None:
    connection.execute(
        text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
        {"workspace_id": workspace_id},
    )


def _approve(journey: Journey, decision_id: str):
    return journey.post(
        f"/compliance-decisions/{decision_id}/approve",
        json={"comment": "PG validated"},
    )


def test_alembic_migration_on_clean_postgresql(postgresql_url: str):
    engine = create_engine(postgresql_url)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            policies = connection.scalar(
                text("SELECT count(*) FROM pg_policies WHERE policyname = 'workspace_isolation'")
            )
            triggers = set(
                connection.scalars(
                    text(
                        "SELECT tgname FROM pg_trigger "
                        "WHERE NOT tgisinternal AND tgname IN "
                        "('document_versions_immutable', 'approved_decisions_immutable', "
                        "'approved_decision_requires_evidence', "
                        "'approved_decision_links_immutable', 'response_snapshot_immutable')"
                    )
                )
            )
            role = connection.execute(
                text(
                    "SELECT current_user, rolsuper, rolbypassrls FROM pg_roles "
                    "WHERE rolname = current_user"
                )
            ).one()
        assert revision == "c7a0e11f6b42"
        assert role.current_user == "ctrl_v2_runtime"
        assert role.rolsuper is False
        assert role.rolbypassrls is False
        assert len(inspect(engine).get_table_names()) == 30
        assert policies == 27
        assert triggers == {
            "document_versions_immutable",
            "approved_decisions_immutable",
            "approved_decision_requires_evidence",
            "approved_decision_links_immutable",
            "response_snapshot_immutable",
        }
    finally:
        engine.dispose()


def test_postgresql_rls_and_application_worker_context(pg_client, postgresql_url: str):
    first = Journey(pg_client, "PG First")
    second = Journey(pg_client, "PG Second")
    document = first.upload("Workspace one only", "RFP", "isolated.xlsx")
    version_id = document["document_version_id"]

    factory = pg_client.app.state.workflow.uow_factory
    with factory(first.workspace_id) as uow:
        assert uow.repo.get_document_version(version_id) is not None
    with factory(second.workspace_id) as uow:
        assert uow.repo.get_document_version(version_id) is None

    worker_database = Database(postgresql_url)
    worker_factory = SqlAlchemyUnitOfWorkFactory(worker_database.session_factory)
    try:
        with worker_factory(first.workspace_id) as uow:
            assert uow.repo.get_document_version(version_id) is not None
        with worker_factory(second.workspace_id) as uow:
            assert uow.repo.get_document_version(version_id) is None
    finally:
        worker_database.engine.dispose()

    engine = create_engine(postgresql_url)
    try:
        with engine.begin() as connection:
            _set_workspace(connection, second.workspace_id)
            visible = connection.scalar(
                text("SELECT count(*) FROM document_versions WHERE id = :version_id"),
                {"version_id": version_id},
            )
            assert visible == 0
        with engine.connect() as connection:
            transaction = connection.begin()
            _set_workspace(connection, second.workspace_id)
            with pytest.raises(DBAPIError):
                connection.execute(
                    text(
                        "INSERT INTO documents "
                        "(workspace_id, id, title, kind, original_filename, status, created_at) "
                        "VALUES (:workspace_id, gen_random_uuid()::text, 'x', 'RFP', 'x', "
                        "'ACTIVE', now())"
                    ),
                    {"workspace_id": first.workspace_id},
                )
            transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.parametrize("outcome", ["COMPLY", "PARTIAL"])
def test_deferred_approved_positive_decision_requires_evidence_span(
    pg_client, postgresql_url: str, outcome: str
):
    journey = Journey(pg_client, f"Deferred {outcome}")
    state = journey.build_until_decision(with_evidence=False)
    decision_id = state["decision"]["id"]
    engine = create_engine(postgresql_url)
    connection = engine.connect()
    transaction = connection.begin()
    try:
        _set_workspace(connection, journey.workspace_id)
        connection.execute(
                text(
                    "UPDATE compliance_decisions SET outcome = :outcome, status = 'APPROVED', "
                    "approved_by_principal_id = ("
                    "SELECT id FROM principals WHERE issuer = 'urn:ctrl-v2:development' "
                    "AND subject = 'operator') "
                    "WHERE workspace_id = :workspace_id AND id = :decision_id"
                ),
            {
                "outcome": outcome,
                "workspace_id": journey.workspace_id,
                "decision_id": decision_id,
            },
        )
        assert transaction.is_active
        with pytest.raises(DBAPIError, match="requires an exact EvidenceSpan"):
            transaction.commit()
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        engine.dispose()


def test_document_version_is_immutable_in_postgresql(pg_client, postgresql_url: str):
    journey = Journey(pg_client, "Immutable DocumentVersion")
    document = journey.upload("Immutable source", "RFP", "immutable.xlsx")
    engine = create_engine(postgresql_url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            _set_workspace(connection, journey.workspace_id)
            with pytest.raises(DBAPIError, match="DocumentVersion is immutable"):
                connection.execute(
                    text(
                        "UPDATE document_versions SET sha256 = :sha "
                        "WHERE workspace_id = :workspace_id AND id = :version_id"
                    ),
                    {
                        "sha": "0" * 64,
                        "workspace_id": journey.workspace_id,
                        "version_id": document["document_version_id"],
                    },
                )
            transaction.rollback()
    finally:
        engine.dispose()


def test_approved_decision_is_immutable_in_postgresql(pg_client, postgresql_url: str):
    journey = Journey(pg_client, "Immutable Decision")
    state = journey.build_until_decision()
    assert _approve(journey, state["decision"]["id"]).status_code == 200
    engine = create_engine(postgresql_url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            _set_workspace(connection, journey.workspace_id)
            with pytest.raises(DBAPIError, match="Approved ComplianceDecision is immutable"):
                connection.execute(
                    text(
                        "UPDATE compliance_decisions SET rationale = 'tampered' "
                        "WHERE workspace_id = :workspace_id AND id = :decision_id"
                    ),
                    {
                        "workspace_id": journey.workspace_id,
                        "decision_id": state["decision"]["id"],
                    },
                )
            transaction.rollback()
    finally:
        engine.dispose()


def test_response_snapshot_is_immutable_in_postgresql(pg_client, postgresql_url: str):
    journey = Journey(pg_client, "Immutable Response")
    state = journey.build_until_decision()
    assert _approve(journey, state["decision"]["id"]).status_code == 200
    response = journey.post(
        "/responses",
        json={"rfp_id": state["rfp"]["id"], "decision_ids": [state["decision"]["id"]]},
    )
    assert response.status_code == 201, response.text
    engine = create_engine(postgresql_url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            _set_workspace(connection, journey.workspace_id)
            with pytest.raises(DBAPIError, match="Response snapshot is immutable"):
                connection.execute(
                    text(
                        "UPDATE responses SET snapshot_hash = :hash "
                        "WHERE workspace_id = :workspace_id AND id = :response_id"
                    ),
                    {
                        "hash": "f" * 64,
                        "workspace_id": journey.workspace_id,
                        "response_id": response.json()["id"],
                    },
                )
            transaction.rollback()
    finally:
        engine.dispose()
