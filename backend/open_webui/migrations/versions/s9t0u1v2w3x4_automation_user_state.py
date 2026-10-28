"""Add automation_user_state: whether a task is pinned in a user's sidebar,
and the last run the user has seen.

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-10-28 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "s9t0u1v2w3x4"
down_revision = "r8s9t0u1v2w3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "automation_user_state",
        sa.Column("user_id", sa.Text(), primary_key=True),
        sa.Column("automation_id", sa.Text(), primary_key=True),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("seen_run_id", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        "ix_automation_user_state_automation_id",
        "automation_user_state",
        ["automation_id"],
    )


def downgrade():
    op.drop_index(
        "ix_automation_user_state_automation_id", table_name="automation_user_state"
    )
    op.drop_table("automation_user_state")
