"""Allow per-user skill packs for the same git_url@ref

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-27 00:00:00.000000

"""

from alembic import op

revision = "g7h8i9j0k1l2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("uq_skill_pack_git_url_ref", table_name="skill_pack")
    op.create_index(
        "uq_skill_pack_user_git_url_ref",
        "skill_pack",
        ["user_id", "git_url", "git_ref"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_skill_pack_user_git_url_ref", table_name="skill_pack")
    op.create_index(
        "uq_skill_pack_git_url_ref",
        "skill_pack",
        ["git_url", "git_ref"],
        unique=True,
    )
