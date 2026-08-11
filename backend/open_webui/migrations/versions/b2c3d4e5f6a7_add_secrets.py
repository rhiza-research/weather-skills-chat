"""Add encrypted secret store

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-11 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "secret",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("team_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_secret_user_id", "secret", ["user_id"])
    op.create_index("ix_secret_team_id", "secret", ["team_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_secret_personal_name "
        "ON secret (user_id, name) WHERE team_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_secret_team_name "
        "ON secret (team_id, name) WHERE team_id IS NOT NULL"
    )


def downgrade():
    op.drop_index("uq_secret_team_name", table_name="secret")
    op.drop_index("uq_secret_personal_name", table_name="secret")
    op.drop_index("ix_secret_team_id", table_name="secret")
    op.drop_index("ix_secret_user_id", table_name="secret")
    op.drop_table("secret")
