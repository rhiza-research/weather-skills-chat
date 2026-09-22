"""Add organization-scoped preferences.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-09-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "o5p6q7r8s9t0"
down_revision = "n4o5p6q7r8s9"
branch_labels = None
depends_on = None


def upgrade():
    if "preference" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "preference",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="private"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_preference_organization_id", "preference", ["organization_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_preference_private_title "
        "ON preference (organization_id, user_id, title) WHERE visibility = 'private'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_preference_organization_title "
        "ON preference (organization_id, title) WHERE visibility = 'organization'"
    )


def downgrade():
    if "preference" not in inspect(op.get_bind()).get_table_names():
        return
    op.execute("DROP INDEX IF EXISTS uq_preference_organization_title")
    op.execute("DROP INDEX IF EXISTS uq_preference_private_title")
    op.drop_index("ix_preference_organization_id", table_name="preference")
    op.drop_table("preference")
