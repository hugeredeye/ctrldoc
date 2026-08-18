"""Foundation validation fixes for PostgreSQL.

Revision ID: 4b6c3a9e2d11
Revises: 9f78f0e1f10d
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "4b6c3a9e2d11"
down_revision: str | None = "9f78f0e1f10d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION ctrl_protect_response_snapshot() RETURNS trigger AS $$
            BEGIN
                IF OLD.snapshot_hash IS DISTINCT FROM NEW.snapshot_hash
                   OR OLD.snapshot_json::jsonb IS DISTINCT FROM NEW.snapshot_json::jsonb
                   OR OLD.rfp_id IS DISTINCT FROM NEW.rfp_id
                   OR OLD.assessment_as_of IS DISTINCT FROM NEW.assessment_as_of
                   OR OLD.version_no IS DISTINCT FROM NEW.version_no THEN
                    RAISE EXCEPTION 'Response snapshot is immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION ctrl_protect_response_snapshot() RETURNS trigger AS $$
            BEGIN
                IF OLD.snapshot_hash IS DISTINCT FROM NEW.snapshot_hash
                   OR OLD.snapshot_json::text IS DISTINCT FROM NEW.snapshot_json::text
                   OR OLD.rfp_id IS DISTINCT FROM NEW.rfp_id
                   OR OLD.assessment_as_of IS DISTINCT FROM NEW.assessment_as_of
                   OR OLD.version_no IS DISTINCT FROM NEW.version_no THEN
                    RAISE EXCEPTION 'Response snapshot is immutable';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
