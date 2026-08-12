"""Add skill packs for git-installed agent skills

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-08-11 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "skill_pack",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False, unique=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("git_url", sa.Text(), nullable=False),
        sa.Column("git_ref", sa.Text(), nullable=False),
        sa.Column("commit_sha", sa.Text(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_skill_pack_user_id", "skill_pack", ["user_id"])
    op.create_index(
        "uq_skill_pack_git_url_ref",
        "skill_pack",
        ["git_url", "git_ref"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_skill_pack_git_url_ref", table_name="skill_pack")
    op.drop_index("ix_skill_pack_user_id", table_name="skill_pack")
    op.drop_table("skill_pack")
