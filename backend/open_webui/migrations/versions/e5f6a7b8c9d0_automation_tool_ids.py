"""Add tool_ids and features to automation

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-12 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("automation", sa.Column("tool_ids", sa.JSON(), nullable=True))
    op.add_column("automation", sa.Column("features", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("automation", "features")
    op.drop_column("automation", "tool_ids")
