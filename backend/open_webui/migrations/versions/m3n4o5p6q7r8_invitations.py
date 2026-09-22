"""Invitation tokens for platform and organization invites.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-09-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "m3n4o5p6q7r8"
down_revision = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade():
    if _table_exists("invitation"):
        return
    op.create_table(
        "invitation",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("organization_id", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("accepted_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("invitation_token_hash", "invitation", ["token_hash"], unique=True)
    op.create_index("invitation_email_kind", "invitation", ["email", "kind"])


def downgrade():
    if not _table_exists("invitation"):
        return
    op.drop_index("invitation_email_kind", table_name="invitation")
    op.drop_index("invitation_token_hash", table_name="invitation")
    op.drop_table("invitation")
