"""Record when an MCP OAuth refresh token was rotated

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2026-09-22 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "t0u1v2w3x4y5"
down_revision = "s9t0u1v2w3x4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("mcp_oauth_token", sa.Column("rotated_at", sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column("mcp_oauth_token", "rotated_at")
