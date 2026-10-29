"""Add a scheduled task's optional picture: automation_image holds it, and
automation.image_updated_at says whether there is one and when it changed.

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2026-10-28 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "t0u1v2w3x4y5"
down_revision = "s9t0u1v2w3x4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "automation", sa.Column("image_updated_at", sa.BigInteger(), nullable=True)
    )
    op.create_table(
        "automation_image",
        sa.Column("automation_id", sa.Text(), primary_key=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )


def downgrade():
    op.drop_table("automation_image")
    op.drop_column("automation", "image_updated_at")
