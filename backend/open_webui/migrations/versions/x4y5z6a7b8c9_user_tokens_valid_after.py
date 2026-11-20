"""Add user.tokens_valid_after.

Sign-in tokens issued before this time are rejected. Signing out of all
devices and changing a password set it to the current time.

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-11-18 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "x4y5z6a7b8c9"
down_revision = "w3x4y5z6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user", sa.Column("tokens_valid_after", sa.BigInteger(), nullable=True)
    )


def downgrade():
    op.drop_column("user", "tokens_valid_after")
