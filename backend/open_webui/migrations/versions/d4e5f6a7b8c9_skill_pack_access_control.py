"""Add access_control to skill packs

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-08-11 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("skill_pack", sa.Column("access_control", sa.JSON(), nullable=True))
    # Existing packs were installed as private toolkits ({}); treat unset as private.
    op.execute("UPDATE skill_pack SET access_control = '{}' WHERE access_control IS NULL")


def downgrade():
    op.drop_column("skill_pack", "access_control")
