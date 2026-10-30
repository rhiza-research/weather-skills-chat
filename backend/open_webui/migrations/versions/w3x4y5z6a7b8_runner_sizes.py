"""Add organization.can_use_large_runners and automation.runner_type.

can_use_large_runners lets an organization's members use tool runner sizes
that need approval. It starts on for every organization. runner_type is the tool runner size a scheduled task's
runs use; tasks without one use the default size.

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-10-29 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "w3x4y5z6a7b8"
down_revision = "v2w3x4y5z6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "organization",
        sa.Column(
            "can_use_large_runners",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column("automation", sa.Column("runner_type", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("automation", "runner_type")
    op.drop_column("organization", "can_use_large_runners")
