"""Catalog access: public platform items, per-org enablement, can_add flags.

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-09-18 00:00:00.000000

"""

import json
import shutil
from pathlib import Path

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "j0k1l2m3n4o5"
down_revision = "i9j0k1l2m3n4"
branch_labels = None
depends_on = None

PLATFORM_ORG_ID = "platform"


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _add_bool(table: str, name: str, default: bool = False) -> None:
    if name in _column_names(table):
        return
    op.add_column(
        table,
        sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true() if default else sa.false()),
    )


def upgrade():
    conn = op.get_bind()

    for flag in ("can_add_models", "can_add_skills", "can_add_knowledge"):
        _add_bool("organization", flag, False)

    if "organization_id" not in _column_names("model"):
        op.add_column("model", sa.Column("organization_id", sa.Text(), nullable=True))
    if "visibility" not in _column_names("model"):
        op.add_column("model", sa.Column("visibility", sa.Text(), nullable=True))
    _add_bool("model", "enabled_by_default", True)

    conn.execute(
        text(
            "UPDATE model SET organization_id = :platform, visibility = 'public' "
            "WHERE organization_id IS NULL"
        ),
        {"platform": PLATFORM_ORG_ID},
    )
    with op.batch_alter_table("model") as batch:
        batch.alter_column("organization_id", existing_type=sa.Text(), nullable=False)
        batch.alter_column("visibility", existing_type=sa.Text(), nullable=False)

    if "organization_id" not in _column_names("knowledge"):
        op.add_column("knowledge", sa.Column("organization_id", sa.Text(), nullable=True))
    if "visibility" not in _column_names("knowledge"):
        op.add_column("knowledge", sa.Column("visibility", sa.Text(), nullable=True))
    _add_bool("knowledge", "enabled_by_default", True)
    conn.execute(
        text(
            "UPDATE knowledge SET organization_id = :platform, visibility = 'public', "
            "enabled_by_default = true WHERE access_control IS NULL"
        ),
        {"platform": PLATFORM_ORG_ID},
    )

    if _table_exists("skill_pack"):
        rows = conn.execute(text("SELECT id, local_path, meta FROM skill_pack")).fetchall()
        tool_ids = []
        for _pack_id, local_path, meta in rows:
            if local_path:
                shutil.rmtree(local_path, ignore_errors=True)
            data = meta
            if isinstance(meta, str):
                try:
                    data = json.loads(meta) if meta.strip() else {}
                except Exception:
                    data = {}
            if isinstance(data, dict):
                for skill in data.get("skills") or []:
                    if isinstance(skill, dict) and skill.get("tool_id"):
                        tool_ids.append(skill["tool_id"])
            parent = Path(local_path).parent if local_path else None
            if parent and parent.exists() and parent.name.startswith("skills"):
                pass
        if tool_ids and _table_exists("tool"):
            for tool_id in tool_ids:
                conn.execute(text("DELETE FROM tool WHERE id = :id"), {"id": tool_id})
        conn.execute(text("DELETE FROM skill_pack"))
        _add_bool("skill_pack", "enabled_by_default", True)

    if not _table_exists("org_catalog_override"):
        op.create_table(
            "org_catalog_override",
            sa.Column("organization_id", sa.Text(), nullable=False),
            sa.Column("resource_type", sa.Text(), nullable=False),
            sa.Column("resource_id", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint(
                "organization_id", "resource_type", "resource_id"
            ),
        )


def downgrade():
    if _table_exists("org_catalog_override"):
        op.drop_table("org_catalog_override")
    for table, cols in (
        ("organization", ("can_add_models", "can_add_skills", "can_add_knowledge")),
        ("model", ("organization_id", "visibility", "enabled_by_default")),
        ("knowledge", ("enabled_by_default",)),
        ("skill_pack", ("enabled_by_default",)),
    ):
        if not _table_exists(table):
            continue
        existing = _column_names(table)
        for col in cols:
            if col in existing:
                op.drop_column(table, col)
