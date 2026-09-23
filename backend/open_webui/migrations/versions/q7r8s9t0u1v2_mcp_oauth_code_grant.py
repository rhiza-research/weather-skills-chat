"""Record the grant issued for each MCP OAuth code

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-09-22 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "q7r8s9t0u1v2"
down_revision = "p6q7r8s9t0u1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("mcp_oauth_code", sa.Column("grant_id", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("mcp_oauth_code", "grant_id")
