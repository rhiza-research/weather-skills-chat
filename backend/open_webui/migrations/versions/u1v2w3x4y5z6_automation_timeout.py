"""Add automation.timeout_minutes, how long a scheduled task's run may take.

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-10-29 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "u1v2w3x4y5z6"
down_revision = "t0u1v2w3x4y5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "automation", sa.Column("timeout_minutes", sa.Integer(), nullable=True)
    )


def downgrade():
    op.drop_column("automation", "timeout_minutes")
