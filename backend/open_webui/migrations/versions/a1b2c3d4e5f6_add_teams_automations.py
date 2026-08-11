"""Add teams, team members, chat.team_id, automations

Revision ID: a1b2c3d4e5f6
Revises: 3781e22d8b01
Create Date: 2026-08-11 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f6"
down_revision = "3781e22d8b01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "team",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )

    op.create_table(
        "team_member",
        sa.Column("team_id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("team_id", "user_id"),
    )
    op.create_index("ix_team_member_user_id", "team_member", ["user_id"])

    op.add_column("chat", sa.Column("team_id", sa.Text(), nullable=True))
    op.create_index("ix_chat_team_id", "chat", ["team_id"])

    op.create_table(
        "automation",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False, unique=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("cron", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("team_id", sa.Text(), nullable=True),
        sa.Column("source_chat_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.BigInteger(), nullable=True),
        sa.Column("updated_at", sa.BigInteger(), nullable=True),
    )
    op.create_index("ix_automation_user_id", "automation", ["user_id"])
    op.create_index("ix_automation_team_id", "automation", ["team_id"])

    op.create_table(
        "automation_run",
        sa.Column("id", sa.Text(), primary_key=True, nullable=False, unique=True),
        sa.Column("automation_id", sa.Text(), nullable=False),
        sa.Column("chat_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.BigInteger(), nullable=True),
        sa.Column("finished_at", sa.BigInteger(), nullable=True),
        sa.Column("triggered_by", sa.Text(), nullable=True),
    )
    op.create_index("ix_automation_run_automation_id", "automation_run", ["automation_id"])


def downgrade():
    op.drop_index("ix_automation_run_automation_id", table_name="automation_run")
    op.drop_table("automation_run")
    op.drop_index("ix_automation_team_id", table_name="automation")
    op.drop_index("ix_automation_user_id", table_name="automation")
    op.drop_table("automation")
    op.drop_index("ix_chat_team_id", table_name="chat")
    op.drop_column("chat", "team_id")
    op.drop_index("ix_team_member_user_id", table_name="team_member")
    op.drop_table("team_member")
    op.drop_table("team")
