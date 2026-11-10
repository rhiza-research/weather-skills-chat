"""Add text skills: markdown instructions scoped like preferences.

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-11-09 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "x4y5z6a7b8c9"
down_revision = "w3x4y5z6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    if "text_skill" in inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "text_skill",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=False),
        sa.Column("visibility", sa.Text(), nullable=False, server_default="private"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "enabled_by_default", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_text_skill_organization_id", "text_skill", ["organization_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_text_skill_private_title "
        "ON text_skill (organization_id, user_id, title) WHERE visibility = 'private'"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_text_skill_organization_title "
        "ON text_skill (organization_id, title) WHERE visibility = 'organization'"
    )


def downgrade():
    if "text_skill" not in inspect(op.get_bind()).get_table_names():
        return
    op.execute("DROP INDEX IF EXISTS uq_text_skill_organization_title")
    op.execute("DROP INDEX IF EXISTS uq_text_skill_private_title")
    op.drop_index("ix_text_skill_organization_id", table_name="text_skill")
    op.drop_table("text_skill")
