"""Production authentication and accountable authorization boundary.

Revision ID: c7a0e11f6b42
Revises: 8d4f2a1c7b90
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c7a0e11f6b42"
down_revision: str | None = "8d4f2a1c7b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        raise RuntimeError("The authentication boundary requires PostgreSQL")

    op.create_table(
        "principals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("issuer", sa.String(length=500), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("principal_type", sa.String(length=20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "principal_type IN ('USER', 'SERVICE')",
            name="principal_type_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issuer", "subject"),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("principal_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "role IN ('VIEWER', 'EDITOR', 'APPROVER', 'ADMIN')",
            name="workspace_membership_role_valid",
        ),
        sa.ForeignKeyConstraint(["principal_id"], ["principals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "principal_id"),
    )

    op.add_column(
        "compliance_decisions",
        sa.Column("approved_by_principal_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "human_reviews",
        sa.Column("reviewer_principal_id", sa.String(length=36), nullable=True),
    )

    op.execute(sa.text("ALTER TABLE compliance_decisions DISABLE TRIGGER approved_decisions_immutable"))
    op.execute(
        sa.text(
            "ALTER TABLE compliance_decisions "
            "DISABLE TRIGGER approved_decision_requires_evidence"
        )
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
                    INSERT INTO principals (
                        id, issuer, subject, principal_type, active, created_at
                    )
                    SELECT
                        gen_random_uuid()::text,
                        'urn:ctrl-v2:legacy-reviewer',
                        legacy.subject,
                        'USER',
                        false,
                        now()
                    FROM (
                        SELECT reviewer_subject AS subject
                        FROM human_reviews
                        WHERE workspace_id = workspace.id
                        UNION
                        SELECT approved_by AS subject
                        FROM compliance_decisions
                        WHERE workspace_id = workspace.id AND approved_by IS NOT NULL
                    ) legacy
                    ON CONFLICT (issuer, subject) DO NOTHING;

                    UPDATE compliance_decisions decisions
                    SET approved_by_principal_id = principals.id
                    FROM principals
                    WHERE decisions.workspace_id = workspace.id
                      AND principals.issuer = 'urn:ctrl-v2:legacy-reviewer'
                      AND principals.subject = decisions.approved_by
                      AND decisions.approved_by IS NOT NULL;

                    UPDATE human_reviews reviews
                    SET reviewer_principal_id = principals.id
                    FROM principals
                    WHERE reviews.workspace_id = workspace.id
                      AND principals.issuer = 'urn:ctrl-v2:legacy-reviewer'
                      AND principals.subject = reviews.reviewer_subject;
                END LOOP;
                PERFORM set_config('app.workspace_id', '', true);
            END;
            $$;
            """
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE compliance_decisions "
            "ENABLE TRIGGER approved_decision_requires_evidence"
        )
    )
    op.execute(sa.text("ALTER TABLE compliance_decisions ENABLE TRIGGER approved_decisions_immutable"))
    op.alter_column("human_reviews", "reviewer_principal_id", nullable=False)
    op.create_foreign_key(
        "compliance_decisions_approved_by_principal_id_fkey",
        "compliance_decisions",
        "principals",
        ["approved_by_principal_id"],
        ["id"],
    )
    op.create_foreign_key(
        "human_reviews_reviewer_principal_id_fkey",
        "human_reviews",
        "principals",
        ["reviewer_principal_id"],
        ["id"],
    )
    op.create_check_constraint(
        "approved_decision_has_principal",
        "compliance_decisions",
        "status <> 'APPROVED' OR approved_by_principal_id IS NOT NULL",
    )
    op.drop_column("compliance_decisions", "approved_by")
    op.drop_column("human_reviews", "reviewer_subject")
    op.drop_column("workspaces", "access_token_hash")

    op.execute(
        sa.text(
            """
            ALTER TABLE workspace_memberships ENABLE ROW LEVEL SECURITY;
            ALTER TABLE workspace_memberships FORCE ROW LEVEL SECURITY;
            CREATE POLICY workspace_isolation ON workspace_memberships
                USING (
                    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')
                )
                WITH CHECK (
                    workspace_id = NULLIF(current_setting('app.workspace_id', true), '')
                );

            REVOKE ALL PRIVILEGES ON TABLE principals, workspace_memberships FROM PUBLIC;
            REVOKE ALL PRIVILEGES ON TABLE principals, workspace_memberships
                FROM ctrl_v2_migrator, ctrl_v2_runtime;
            GRANT SELECT, INSERT ON TABLE principals TO ctrl_v2_runtime;
            GRANT SELECT, INSERT, UPDATE ON TABLE workspace_memberships TO ctrl_v2_runtime;
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading the production authentication boundary would destroy accountable identity"
    )
