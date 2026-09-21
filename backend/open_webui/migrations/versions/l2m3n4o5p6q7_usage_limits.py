"""Org/user monthly usage limits, ledger, and rollups.

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-09-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def upgrade():
    conn = op.get_bind()

    if _table_exists("organization") and "monthly_limit_usd" not in _column_names(
        "organization"
    ):
        op.add_column(
            "organization",
            sa.Column("monthly_limit_usd", sa.Float(), nullable=True),
        )
        conn.execute(
            text(
                "UPDATE organization SET monthly_limit_usd = 300 "
                "WHERE kind IS NULL OR kind != 'platform'"
            )
        )

    if _table_exists("organization_member") and "monthly_limit_usd" not in _column_names(
        "organization_member"
    ):
        op.add_column(
            "organization_member",
            sa.Column("monthly_limit_usd", sa.Float(), nullable=True),
        )

    if not _table_exists("usage_event"):
        op.create_table(
            "usage_event",
            sa.Column("id", sa.Text(), nullable=False),
            sa.Column("created_at", sa.BigInteger(), nullable=False),
            sa.Column("organization_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("chat_id", sa.Text(), nullable=True),
            sa.Column("message_id", sa.Text(), nullable=True),
            sa.Column("model_id", sa.Text(), nullable=True),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False),
            sa.Column("completion_tokens", sa.Integer(), nullable=False),
            sa.Column("total_tokens", sa.Integer(), nullable=False),
            sa.Column("cached_tokens", sa.Integer(), nullable=False),
            sa.Column("uncached_tokens", sa.Integer(), nullable=False),
            sa.Column("cost_usd", sa.Float(), nullable=False),
            sa.Column("period", sa.Text(), nullable=False),
            sa.Column("raw", sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_usage_event_org_period",
            "usage_event",
            ["organization_id", "period"],
        )
        op.create_index(
            "ix_usage_event_org_user_period",
            "usage_event",
            ["organization_id", "user_id", "period"],
        )
        op.create_index("ix_usage_event_created_at", "usage_event", ["created_at"])

    if not _table_exists("usage_month"):
        op.create_table(
            "usage_month",
            sa.Column("organization_id", sa.Text(), nullable=False),
            sa.Column("user_id", sa.Text(), nullable=False),
            sa.Column("period", sa.Text(), nullable=False),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False),
            sa.Column("completion_tokens", sa.Integer(), nullable=False),
            sa.Column("total_tokens", sa.Integer(), nullable=False),
            sa.Column("cached_tokens", sa.Integer(), nullable=False),
            sa.Column("uncached_tokens", sa.Integer(), nullable=False),
            sa.Column("cost_usd", sa.Float(), nullable=False),
            sa.PrimaryKeyConstraint("organization_id", "user_id", "period"),
        )


def downgrade():
    if _table_exists("usage_event"):
        op.drop_index("ix_usage_event_created_at", table_name="usage_event")
        op.drop_index("ix_usage_event_org_user_period", table_name="usage_event")
        op.drop_index("ix_usage_event_org_period", table_name="usage_event")
        op.drop_table("usage_event")
    if _table_exists("usage_month"):
        op.drop_table("usage_month")
    if _table_exists("organization_member") and "monthly_limit_usd" in _column_names(
        "organization_member"
    ):
        op.drop_column("organization_member", "monthly_limit_usd")
    if _table_exists("organization") and "monthly_limit_usd" in _column_names(
        "organization"
    ):
        op.drop_column("organization", "monthly_limit_usd")
