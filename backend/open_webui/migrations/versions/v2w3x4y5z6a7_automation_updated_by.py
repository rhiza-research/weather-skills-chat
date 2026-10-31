"""Add automation.updated_by, the user who last changed a scheduled task.

Tasks changed before this have none.

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-10-29 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "v2w3x4y5z6a7"
down_revision = "u1v2w3x4y5z6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("automation", sa.Column("updated_by", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("automation", "updated_by")
