"""Add organization.logo for a cropped JPEG data URL.

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-09-24 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "p6q7r8s9t0u1"
down_revision = "o5p6q7r8s9t0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organization", sa.Column("logo", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("organization", "logo")
