from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from ctrl_v2.interfaces.http.app import create_app
from ctrl_v2.interfaces.http.config import Settings
from tests.helpers import Journey

SNAPSHOT_TABLES = (
    "workspaces",
    "documents",
    "document_versions",
    "document_representations",
    "document_blocks",
    "rfps",
    "requirements",
    "requirement_source_spans",
    "products",
    "product_versions",
    "capabilities",
    "product_version_capabilities",
    "product_version_documents",
    "requirement_mappings",
    "evidence",
    "evidence_spans",
    "compliance_decisions",
    "decision_evidence_spans",
    "human_reviews",
    "responses",
    "response_items",
)

ROW_QUERIES = {
    "workspaces": """
        SELECT id, name, status FROM workspaces ORDER BY id
    """,
    "documents": """
        SELECT workspace_id, id, title, kind, original_filename, status
        FROM documents ORDER BY workspace_id, id
    """,
    "document_versions": """
        SELECT workspace_id, id, document_id, version_no, object_key, sha256,
               media_type, size_bytes, published_at, processing_status
        FROM document_versions ORDER BY workspace_id, id
    """,
    "requirements": """
        SELECT workspace_id, id, rfp_id, source_order, atomic_text, modality,
               confidence, status
        FROM requirements ORDER BY workspace_id, id
    """,
    "requirement_mappings": """
        SELECT workspace_id, id, requirement_id, product_version_id, capability_id,
               rationale, confidence, status
        FROM requirement_mappings ORDER BY workspace_id, id
    """,
    "evidence": """
        SELECT workspace_id, id, requirement_id, product_version_id, summary,
               source_type, authority_level, valid_from, valid_to, status
        FROM evidence ORDER BY workspace_id, id
    """,
    "evidence_spans": """
        SELECT workspace_id, id, evidence_id, document_version_id, representation_id,
               document_block_id, start_offset, end_offset, exact_quote, quote_hash,
               format_locator
        FROM evidence_spans ORDER BY workspace_id, id
    """,
    "compliance_decisions": """
        SELECT workspace_id, id, requirement_id, product_version_id, mapping_id,
               outcome, rationale, confidence, risk, assessment_as_of, status,
               {approved_actor} AS approved_actor, revision
        FROM compliance_decisions ORDER BY workspace_id, id
    """,
    "responses": """
        SELECT workspace_id, id, rfp_id, version_no, assessment_as_of, status,
               snapshot_hash, snapshot_json
        FROM responses ORDER BY workspace_id, id
    """,
}


def _required_environment(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _json_value(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def snapshot(database_url: str) -> dict[str, Any]:
    engine = create_engine(database_url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            decision_columns = {
                column["name"]
                for column in inspect(connection).get_columns("compliance_decisions")
            }
            approved_actor = (
                "approved_by_principal_id"
                if "approved_by_principal_id" in decision_columns
                else "approved_by"
            )
            counts = {
                table: int(connection.scalar(text(f'SELECT count(*) FROM "{table}"')) or 0)
                for table in SNAPSHOT_TABLES
            }
            records = {
                name: [
                    {key: _json_value(value) for key, value in row.items()}
                    for row in connection.execute(
                        text(query.format(approved_actor=approved_actor))
                    ).mappings()
                ]
                for name, query in ROW_QUERIES.items()
            }
    finally:
        engine.dispose()
    preserved = {"counts": counts, "records": records}
    canonical = json.dumps(preserved, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "alembic_revision": revision,
        "preserved": preserved,
        "preservation_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }


def seed() -> None:
    database_url = _required_environment("DATABASE_URL")
    object_storage_root = Path(_required_environment("OBJECT_STORAGE_ROOT"))
    app = create_app(
        Settings(
            database_url=database_url,
            object_storage_root=object_storage_root,
            create_schema=False,
            log_level="WARNING",
            environment="test",
            auth_mode="dev",
            dev_auth_enabled=True,
            provisioning_principals={"urn:ctrl-v2:development|operator"},
        )
    )
    with TestClient(app) as client:
        primary = Journey(client, "Rehearsal Primary")
        primary_state = primary.build_until_decision()
        approval_body = {"comment": "Approved before database hardening"}
        if "access_token" in primary.workspace:
            approval_body["reviewer_subject"] = "upgrade-rehearsal@example.test"
        approval = primary.post(
            f"/compliance-decisions/{primary_state['decision']['id']}/approve",
            json=approval_body,
        )
        assert approval.status_code == 200, approval.text
        response = primary.post(
            "/responses",
            json={
                "rfp_id": primary_state["rfp"]["id"],
                "decision_ids": [primary_state["decision"]["id"]],
            },
        )
        assert response.status_code == 201, response.text

        secondary = Journey(client, "Rehearsal Secondary")
        secondary.build_until_decision()

    write_snapshot(snapshot(_required_environment("ADMIN_DATABASE_URL")))


def write_snapshot(value: dict[str, Any]) -> None:
    output_path = Path(_required_environment("SNAPSHOT_PATH"))
    output_path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")
    print(
        json.dumps(
            {
                "snapshot": str(output_path),
                "alembic_revision": value["alembic_revision"],
                "preservation_sha256": value["preservation_sha256"],
                "counts": value["preserved"]["counts"],
            },
            sort_keys=True,
        )
    )


def compare() -> None:
    before = json.loads(Path(_required_environment("BEFORE_SNAPSHOT_PATH")).read_text())
    after = json.loads(Path(_required_environment("AFTER_SNAPSHOT_PATH")).read_text())
    if before["preserved"] != after["preserved"]:
        raise RuntimeError("Before and after structural data snapshots differ")
    if before["preservation_sha256"] != after["preservation_sha256"]:
        raise RuntimeError("Before and after preservation hashes differ")
    print(
        json.dumps(
            {
                "preserved": True,
                "before_revision": before["alembic_revision"],
                "after_revision": after["alembic_revision"],
                "preservation_sha256": after["preservation_sha256"],
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("seed", "snapshot", "compare"))
    args = parser.parse_args()
    if args.command == "seed":
        seed()
    elif args.command == "snapshot":
        write_snapshot(snapshot(_required_environment("ADMIN_DATABASE_URL")))
    else:
        compare()


if __name__ == "__main__":
    main()
