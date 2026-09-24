"""Record when an MCP OAuth refresh token was rotated

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-09-22 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "s9t0u1v2w3x4"
down_revision = "r8s9t0u1v2w3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("mcp_oauth_token", sa.Column("rotated_at", sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column("mcp_oauth_token", "rotated_at")
