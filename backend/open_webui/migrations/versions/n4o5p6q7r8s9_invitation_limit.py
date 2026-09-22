"""Store the monthly usage limit chosen when an invitation is sent.

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-09-21 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if "invitation" not in inspect(op.get_bind()).get_table_names():
        return
    if "monthly_limit_usd" in _column_names("invitation"):
        return
    op.add_column(
        "invitation",
        sa.Column("monthly_limit_usd", sa.Float(), nullable=True),
    )
    op.execute("UPDATE invitation SET monthly_limit_usd = 300 WHERE monthly_limit_usd IS NULL")


def downgrade():
    if "invitation" not in inspect(op.get_bind()).get_table_names():
        return
    if "monthly_limit_usd" not in _column_names("invitation"):
        return
    op.drop_column("invitation", "monthly_limit_usd")
