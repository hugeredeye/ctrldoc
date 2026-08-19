from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tests.auth_helpers import dev_auth
from tests.helpers import Journey, xlsx_bytes

pytestmark = pytest.mark.postgres


def _principal(client, subject: str) -> dict:
    response = client.get("/api/v1/me", headers=dev_auth(subject))
    assert response.status_code == 200, response.text
    return response.json()


def _add_membership(client, journey: Journey, subject: str, role: str) -> dict:
    principal = _principal(client, subject)
    response = journey.post(
        "/memberships",
        json={"principal_id": principal["id"], "role": role},
    )
    assert response.status_code == 201, response.text
    return principal


def _download_product_document(client, journey: Journey, state: dict, subject: str):
    return client.get(
        f"/api/v1/workspaces/{journey.workspace_id}/document-versions/"
        f"{state['product_document']['document_version_id']}/content",
        headers=dev_auth(subject),
    )


@pytest.mark.parametrize(
    ("role", "mutation_allowed", "approval_allowed"),
    [
        ("VIEWER", False, False),
        ("EDITOR", True, False),
        ("APPROVER", False, True),
        ("ADMIN", True, True),
    ],
)
def test_workspace_role_matrix(client, role, mutation_allowed, approval_allowed):
    journey = Journey(client, f"Role {role}")
    state = journey.build_until_decision()
    subject = f"role-{role.lower()}"
    _add_membership(client, journey, subject, role)
    headers = dev_auth(subject)

    read_response = _download_product_document(client, journey, state, subject)
    mutation_response = client.post(
        f"/api/v1/workspaces/{journey.workspace_id}/products",
        headers=headers,
        json={"name": f"Created by {role}"},
    )
    approval_response = client.post(
        f"/api/v1/workspaces/{journey.workspace_id}/compliance-decisions/"
        f"{state['decision']['id']}/approve",
        headers=headers,
        json={"comment": f"Reviewed by {role}"},
    )

    assert read_response.status_code == 200
    assert mutation_response.status_code == (201 if mutation_allowed else 403)
    assert approval_response.status_code == (200 if approval_allowed else 403)


def test_editor_can_upload_and_edit_draft_but_cannot_approve(client):
    journey = Journey(client, "Editor operations")
    state = journey.build_until_decision()
    subject = "editor-operations"
    _add_membership(client, journey, subject, "EDITOR")
    headers = dev_auth(subject)

    upload = client.post(
        f"/api/v1/workspaces/{journey.workspace_id}/documents",
        headers=headers,
        data={"title": "editor.xlsx", "kind": "RFP", "published_at": "2026-01-01"},
        files={
            "file": (
                "editor.xlsx",
                xlsx_bytes("Editor upload"),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    edit = client.patch(
        f"/api/v1/workspaces/{journey.workspace_id}/compliance-decisions/"
        f"{state['decision']['id']}",
        headers=headers,
        json={"rationale": "Edited by an authorized editor"},
    )
    approve = client.post(
        f"/api/v1/workspaces/{journey.workspace_id}/compliance-decisions/"
        f"{state['decision']['id']}/approve",
        headers=headers,
        json={"comment": "Not permitted"},
    )

    assert upload.status_code == 201, upload.text
    assert edit.status_code == 200, edit.text
    assert approve.status_code == 403


@pytest.mark.parametrize("action", ["reject", "escalate"])
def test_approver_can_reject_or_escalate(client, action):
    journey = Journey(client, f"Approver {action}")
    state = journey.build_until_decision()
    subject = f"approver-{action}"
    _add_membership(client, journey, subject, "APPROVER")

    response = client.post(
        f"/api/v1/workspaces/{journey.workspace_id}/compliance-decisions/"
        f"{state['decision']['id']}/{action}",
        headers=dev_auth(subject),
        json={"comment": f"Decision {action}ed"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == ("REJECTED" if action == "reject" else "IN_REVIEW")


def test_only_admin_can_manage_memberships(client):
    journey = Journey(client, "Membership administration")
    target = _principal(client, "membership-target")
    approver = _add_membership(client, journey, "membership-approver", "APPROVER")

    denied = client.post(
        f"/api/v1/workspaces/{journey.workspace_id}/memberships",
        headers=dev_auth("membership-approver"),
        json={"principal_id": target["id"], "role": "VIEWER"},
    )
    allowed = journey.post(
        "/memberships",
        json={"principal_id": target["id"], "role": "VIEWER"},
    )

    assert approver["id"] != target["id"]
    assert denied.status_code == 403
    assert allowed.status_code == 201, allowed.text


def test_valid_principal_without_membership_is_denied(client):
    journey = Journey(client, "No implicit membership")
    state = journey.build_until_decision()
    _principal(client, "outsider")

    response = _download_product_document(client, journey, state, "outsider")

    assert response.status_code == 403


@pytest.mark.parametrize("role", ["VIEWER", "EDITOR", "APPROVER", "ADMIN"])
def test_cross_workspace_access_is_denied_for_every_role(client, role):
    first = Journey(client, f"Membership source {role}")
    second = Journey(client, f"Foreign workspace {role}")
    foreign_document = second.upload("Foreign tenant document", "RFP", "foreign.xlsx")
    subject = f"cross-{role.lower()}"
    _add_membership(client, first, subject, role)

    response = client.get(
        f"/api/v1/workspaces/{second.workspace_id}/document-versions/"
        f"{foreign_document['document_version_id']}/content",
        headers=dev_auth(subject),
    )

    assert response.status_code == 403
    assert b"Foreign tenant document" not in response.content


def test_disabled_principal_is_denied(client, postgres_urls):
    journey = Journey(client, "Disabled principal")
    state = journey.build_until_decision()
    principal = _add_membership(client, journey, "disabled-principal", "VIEWER")
    engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE principals SET active = false WHERE id = :principal_id"),
                {"principal_id": principal["id"]},
            )
    finally:
        engine.dispose()

    response = _download_product_document(client, journey, state, "disabled-principal")

    assert response.status_code == 401


def test_disabled_membership_is_denied(client):
    journey = Journey(client, "Disabled membership")
    state = journey.build_until_decision()
    principal = _add_membership(client, journey, "disabled-membership", "VIEWER")
    disabled = journey.client.patch(
        f"/api/v1/workspaces/{journey.workspace_id}/memberships/{principal['id']}",
        headers=journey.headers,
        json={"active": False},
    )

    response = _download_product_document(client, journey, state, "disabled-membership")

    assert disabled.status_code == 200, disabled.text
    assert response.status_code == 403


def test_forged_reviewer_is_rejected_and_authenticated_principal_is_stored(
    client, postgres_urls
):
    journey = Journey(client, "Accountable approval")
    state = journey.build_until_decision()
    principal = _add_membership(client, journey, "actual-approver", "APPROVER")
    endpoint = (
        f"/api/v1/workspaces/{journey.workspace_id}/compliance-decisions/"
        f"{state['decision']['id']}/approve"
    )

    forged = client.post(
        endpoint,
        headers=dev_auth("actual-approver"),
        json={"reviewer_subject": "forged@example.test", "comment": "Forged actor"},
    )
    approved = client.post(
        endpoint,
        headers=dev_auth("actual-approver"),
        json={"comment": "Authenticated actor"},
    )

    assert forged.status_code == 422
    assert approved.status_code == 200, approved.text
    assert approved.json()["approved_by_principal_id"] == principal["id"]

    engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with engine.connect() as connection:
            stored = connection.execute(
                text(
                    """
                    SELECT reviews.reviewer_principal_id,
                           decisions.approved_by_principal_id
                    FROM human_reviews reviews
                    JOIN compliance_decisions decisions
                      ON decisions.workspace_id = reviews.workspace_id
                     AND decisions.id = reviews.decision_id
                    WHERE reviews.workspace_id = :workspace_id
                      AND reviews.decision_id = :decision_id
                    """
                ),
                {
                    "workspace_id": journey.workspace_id,
                    "decision_id": state["decision"]["id"],
                },
            ).one()
    finally:
        engine.dispose()
    assert stored.reviewer_principal_id == principal["id"]
    assert stored.approved_by_principal_id == principal["id"]


def test_workspace_provisioning_requires_configured_operator(client):
    _principal(client, "ordinary-user")

    response = client.post(
        "/api/v1/workspaces",
        headers=dev_auth("ordinary-user"),
        json={"name": "Unauthorized provision"},
    )

    assert response.status_code == 403


def test_operator_can_bootstrap_only_a_workspace_without_active_admin(client, postgres_urls):
    legacy_workspace_id = "00000000-0000-0000-0000-00000000c160"
    engine = create_engine(postgres_urls.admin, hide_parameters=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, name, status, created_at) "
                    "VALUES (:id, 'Legacy workspace', 'ACTIVE', now())"
                ),
                {"id": legacy_workspace_id},
            )
    finally:
        engine.dispose()

    bootstrapped = client.post(
        f"/api/v1/operator/workspaces/{legacy_workspace_id}/bootstrap-admin",
        headers=dev_auth("operator"),
    )
    repeated = client.post(
        f"/api/v1/operator/workspaces/{legacy_workspace_id}/bootstrap-admin",
        headers=dev_auth("operator"),
    )
    usable = client.post(
        f"/api/v1/workspaces/{legacy_workspace_id}/products",
        headers=dev_auth("operator"),
        json={"name": "Post-migration product"},
    )

    assert bootstrapped.status_code == 201, bootstrapped.text
    assert bootstrapped.json()["role"] == "ADMIN"
    assert repeated.status_code == 409
    assert usable.status_code == 201, usable.text


def test_non_operator_cannot_bootstrap_workspace_admin(client):
    journey = Journey(client, "Protected bootstrap")
    _principal(client, "not-an-operator")

    response = client.post(
        f"/api/v1/operator/workspaces/{journey.workspace_id}/bootstrap-admin",
        headers=dev_auth("not-an-operator"),
    )

    assert response.status_code == 403


def test_membership_rls_is_fail_closed_at_database_boundary(client, postgres_urls):
    first = Journey(client, "Membership RLS first")
    second = Journey(client, "Membership RLS second")
    principal = _add_membership(client, first, "membership-rls", "VIEWER")
    engine = create_engine(postgres_urls.runtime, hide_parameters=True)
    try:
        with engine.connect() as connection:
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM workspace_memberships "
                        "WHERE principal_id = :principal_id"
                    ),
                    {"principal_id": principal["id"]},
                )
                == 0
            )
        with engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(
                text("SELECT set_config('app.workspace_id', :workspace_id, true)"),
                {"workspace_id": second.workspace_id},
            )
            with pytest.raises(DBAPIError, match="row-level security"):
                connection.execute(
                    text(
                        "INSERT INTO workspace_memberships "
                        "(workspace_id, principal_id, role, active, created_at) "
                        "VALUES (:workspace_id, :principal_id, 'VIEWER', true, now())"
                    ),
                    {
                        "workspace_id": first.workspace_id,
                        "principal_id": principal["id"],
                    },
                )
            transaction.rollback()
    finally:
        engine.dispose()


def test_runtime_cannot_reactivate_or_disable_principals(client, postgres_urls):
    principal = _principal(client, "principal-status-boundary")
    engine = create_engine(postgres_urls.runtime, hide_parameters=True)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            with pytest.raises(DBAPIError, match="permission denied"):
                connection.execute(
                    text("UPDATE principals SET active = false WHERE id = :principal_id"),
                    {"principal_id": principal["id"]},
                )
            transaction.rollback()
    finally:
        engine.dispose()
