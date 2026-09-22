"""Index the MCP OAuth columns that retention filters on

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-09-22 00:00:00.000000

"""

from alembic import op

revision = "r8s9t0u1v2w3"
down_revision = "q7r8s9t0u1v2"
branch_labels = None
depends_on = None

INDEXES = [
    (f"ix_{table}_{column}", table, column)
    for table in ("mcp_oauth_authorization", "mcp_oauth_code", "mcp_oauth_token")
    for column in ("client_id", "expires_at")
]


def upgrade():
    for name, table, column in INDEXES:
        op.create_index(name, table, [column])


def downgrade():
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
