"""Add automation_run.summary for the result a scheduled task's model reports.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-10-28 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "r8s9t0u1v2w3"
down_revision = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("automation_run", sa.Column("summary", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("automation_run", "summary")
