"""Skill catalog membership: pack is_active and per-skill flags.

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-09-21 00:00:00.000000

"""

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def _column_names(table: str) -> set[str]:
    return {col["name"] for col in inspect(op.get_bind()).get_columns(table)}


def _table_exists(name: str) -> bool:
    return name in inspect(op.get_bind()).get_table_names()


def _parse_meta(meta):
    if isinstance(meta, dict):
        return meta
    if isinstance(meta, str) and meta.strip():
        try:
            data = json.loads(meta)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def upgrade():
    conn = op.get_bind()
    if not _table_exists("skill_pack"):
        return

    if "is_active" not in _column_names("skill_pack"):
        op.add_column(
            "skill_pack",
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )

    rows = conn.execute(text("SELECT id, meta FROM skill_pack")).fetchall()
    for pack_id, meta in rows:
        data = _parse_meta(meta)
        skills = data.get("skills") or []
        changed = False
        for skill in skills:
            if not isinstance(skill, dict):
                continue
            if "enabled_by_default" not in skill:
                skill["enabled_by_default"] = skill.get("enabled", True) is not False
                changed = True
            if "enabled" not in skill:
                skill["enabled"] = bool(skill["enabled_by_default"])
                changed = True
            if "is_active" not in skill:
                skill["is_active"] = True
                changed = True
        if not changed:
            continue
        data["skills"] = skills
        conn.execute(
            text("UPDATE skill_pack SET meta = :meta WHERE id = :id"),
            {"meta": json.dumps(data), "id": pack_id},
        )


def downgrade():
    if _table_exists("skill_pack") and "is_active" in _column_names("skill_pack"):
        op.drop_column("skill_pack", "is_active")
