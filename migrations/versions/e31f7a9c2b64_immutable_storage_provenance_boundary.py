"""Immutable storage and evidence provenance boundary.

Revision ID: e31f7a9c2b64
Revises: c7a0e11f6b42
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "e31f7a9c2b64"
down_revision: str | None = "c7a0e11f6b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("The immutable provenance boundary requires PostgreSQL")

    op.add_column(
        "evidence",
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "evidence",
        sa.Column("created_by_principal_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "evidence_supersedes_id_fkey",
        "evidence",
        "evidence",
        ["workspace_id", "supersedes_id"],
        ["workspace_id", "id"],
    )
    op.create_foreign_key(
        "evidence_created_by_principal_id_fkey",
        "evidence",
        "principals",
        ["created_by_principal_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "evidence_supersedes_once",
        "evidence",
        ["workspace_id", "supersedes_id"],
    )
    op.create_check_constraint(
        "evidence_not_self_superseding",
        "evidence",
        "supersedes_id IS NULL OR supersedes_id <> id",
    )
    for table in ("document_versions", "response_exports"):
        op.create_check_constraint(
            f"{table}_sha256_format",
            table,
            "sha256 ~ '^[0-9a-f]{64}$'",
        )
        op.create_check_constraint(
            f"{table}_positive_size",
            table,
            "size_bytes > 0",
        )
        op.create_check_constraint(
            f"{table}_object_key_binds_sha256",
            table,
            "position(sha256 in object_key) > 0",
        )

    op.execute(
        sa.text(
            """
            DO $$
            DECLARE
                workspace record;
            BEGIN
                FOR workspace IN SELECT id FROM workspaces ORDER BY id LOOP
                    PERFORM set_config('app.workspace_id', workspace.id, true);
                    IF EXISTS (
                        SELECT 1
                        FROM response_items items
                        JOIN compliance_decisions decisions
                          ON decisions.workspace_id = items.workspace_id
                         AND decisions.id = items.decision_id
                        WHERE items.workspace_id = workspace.id
                          AND (
                            decisions.status <> 'APPROVED'
                            OR (
                                decisions.outcome IN ('COMPLY', 'PARTIAL')
                                AND NOT EXISTS (
                                    SELECT 1
                                    FROM decision_evidence_spans links
                                    JOIN evidence_spans spans
                                      ON spans.workspace_id = links.workspace_id
                                     AND spans.id = links.evidence_span_id
                                    JOIN evidence evidence_rows
                                      ON evidence_rows.workspace_id = spans.workspace_id
                                     AND evidence_rows.id = spans.evidence_id
                                    JOIN document_versions versions
                                      ON versions.workspace_id = spans.workspace_id
                                     AND versions.id = spans.document_version_id
                                    JOIN document_representations representations
                                      ON representations.workspace_id = spans.workspace_id
                                     AND representations.id = spans.representation_id
                                     AND representations.document_version_id = versions.id
                                    JOIN document_blocks blocks
                                      ON blocks.workspace_id = spans.workspace_id
                                     AND blocks.id = spans.document_block_id
                                     AND blocks.representation_id = representations.id
                                    WHERE links.workspace_id = items.workspace_id
                                      AND links.decision_id = items.decision_id
                                )
                            )
                          )
                    ) THEN
                        RAISE EXCEPTION
                            'Existing ResponseItem has incomplete decision provenance';
                    END IF;
                END LOOP;
                PERFORM set_config('app.workspace_id', '', true);
            END;
            $$;
            """
        )
    )

    op.execute(sa.text("DROP TRIGGER response_snapshot_immutable ON responses"))
    op.execute(sa.text("DROP FUNCTION ctrl_protect_response_snapshot()"))
    op.execute(
        sa.text(
            """
            CREATE FUNCTION ctrl_require_evidence_actor() RETURNS trigger AS $$
            BEGIN
                IF NEW.created_by_principal_id IS NULL THEN
                    RAISE EXCEPTION 'New Evidence requires an authenticated Principal';
                END IF;
                IF NEW.supersedes_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1
                    FROM evidence prior
                    WHERE prior.workspace_id = NEW.workspace_id
                      AND prior.id = NEW.supersedes_id
                      AND prior.requirement_id = NEW.requirement_id
                      AND prior.product_version_id = NEW.product_version_id
                ) THEN
                    RAISE EXCEPTION
                        'Evidence supersession must preserve requirement and ProductVersion scope';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER evidence_requires_actor
            BEFORE INSERT ON evidence
            FOR EACH ROW EXECUTE FUNCTION ctrl_require_evidence_actor();

            CREATE FUNCTION ctrl_protect_referenced_evidence() RETURNS trigger AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM evidence_spans spans
                    JOIN decision_evidence_spans links
                      ON links.workspace_id = spans.workspace_id
                     AND links.evidence_span_id = spans.id
                    WHERE spans.workspace_id = OLD.workspace_id
                      AND spans.evidence_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'Evidence referenced by a decision is immutable';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER referenced_evidence_immutable
            BEFORE UPDATE OR DELETE ON evidence
            FOR EACH ROW EXECUTE FUNCTION ctrl_protect_referenced_evidence();

            CREATE FUNCTION ctrl_protect_referenced_evidence_span() RETURNS trigger AS $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM decision_evidence_spans links
                    WHERE links.workspace_id = OLD.workspace_id
                      AND links.evidence_span_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'EvidenceSpan referenced by a decision is immutable';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER referenced_evidence_spans_immutable
            BEFORE UPDATE OR DELETE ON evidence_spans
            FOR EACH ROW EXECUTE FUNCTION ctrl_protect_referenced_evidence_span();

            CREATE FUNCTION ctrl_protect_evidence_source() RETURNS trigger AS $$
            BEGIN
                IF TG_TABLE_NAME = 'document_representations' AND EXISTS (
                    SELECT 1
                    FROM evidence_spans spans
                    WHERE spans.workspace_id = OLD.workspace_id
                      AND spans.representation_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'DocumentRepresentation used by Evidence is immutable';
                END IF;
                IF TG_TABLE_NAME = 'document_blocks' AND EXISTS (
                    SELECT 1
                    FROM evidence_spans spans
                    WHERE spans.workspace_id = OLD.workspace_id
                      AND spans.document_block_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'DocumentBlock used by Evidence is immutable';
                END IF;
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER evidence_document_representations_immutable
            BEFORE UPDATE OR DELETE ON document_representations
            FOR EACH ROW EXECUTE FUNCTION ctrl_protect_evidence_source();

            CREATE TRIGGER evidence_document_blocks_immutable
            BEFORE UPDATE OR DELETE ON document_blocks
            FOR EACH ROW EXECUTE FUNCTION ctrl_protect_evidence_source();

            CREATE FUNCTION ctrl_reject_append_only_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER human_reviews_append_only
            BEFORE UPDATE OR DELETE ON human_reviews
            FOR EACH ROW EXECUTE FUNCTION ctrl_reject_append_only_mutation();

            CREATE TRIGGER responses_append_only
            BEFORE UPDATE OR DELETE ON responses
            FOR EACH ROW EXECUTE FUNCTION ctrl_reject_append_only_mutation();

            CREATE TRIGGER response_items_append_only
            BEFORE UPDATE OR DELETE ON response_items
            FOR EACH ROW EXECUTE FUNCTION ctrl_reject_append_only_mutation();

            CREATE TRIGGER response_exports_append_only
            BEFORE UPDATE OR DELETE ON response_exports
            FOR EACH ROW EXECUTE FUNCTION ctrl_reject_append_only_mutation();

            CREATE FUNCTION ctrl_validate_response_item_provenance() RETURNS trigger AS $$
            DECLARE
                decision_status text;
                decision_outcome text;
            BEGIN
                SELECT decisions.status, decisions.outcome
                  INTO decision_status, decision_outcome
                  FROM compliance_decisions decisions
                 WHERE decisions.workspace_id = NEW.workspace_id
                   AND decisions.id = NEW.decision_id;
                IF decision_status IS DISTINCT FROM 'APPROVED' THEN
                    RAISE EXCEPTION 'ResponseItem requires an approved ComplianceDecision';
                END IF;
                IF decision_outcome IN ('COMPLY', 'PARTIAL') AND NOT EXISTS (
                    SELECT 1
                    FROM decision_evidence_spans links
                    JOIN evidence_spans spans
                      ON spans.workspace_id = links.workspace_id
                     AND spans.id = links.evidence_span_id
                    JOIN evidence evidence_rows
                      ON evidence_rows.workspace_id = spans.workspace_id
                     AND evidence_rows.id = spans.evidence_id
                    JOIN document_versions versions
                      ON versions.workspace_id = spans.workspace_id
                     AND versions.id = spans.document_version_id
                    JOIN document_representations representations
                      ON representations.workspace_id = spans.workspace_id
                     AND representations.id = spans.representation_id
                     AND representations.document_version_id = versions.id
                    JOIN document_blocks blocks
                      ON blocks.workspace_id = spans.workspace_id
                     AND blocks.id = spans.document_block_id
                     AND blocks.representation_id = representations.id
                    WHERE links.workspace_id = NEW.workspace_id
                      AND links.decision_id = NEW.decision_id
                ) THEN
                    RAISE EXCEPTION 'ResponseItem positive decision provenance is incomplete';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE CONSTRAINT TRIGGER response_items_require_provenance
            AFTER INSERT OR UPDATE ON response_items
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION ctrl_validate_response_item_provenance();

            REVOKE ALL PRIVILEGES ON FUNCTION
                ctrl_require_evidence_actor(),
                ctrl_protect_referenced_evidence(),
                ctrl_protect_referenced_evidence_span(),
                ctrl_protect_evidence_source(),
                ctrl_reject_append_only_mutation(),
                ctrl_validate_response_item_provenance()
            FROM PUBLIC, ctrl_v2_migrator, ctrl_v2_runtime;
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading the immutable provenance boundary would permit historical mutation"
    )
