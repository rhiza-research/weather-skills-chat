"""Keep an automation's skills by name.

Saved skill tool IDs stop matching when a pack is reinstalled, so each run
lost those skills. automation.tool_ids now holds skill names, and IDs for
other tools.

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-10-27 00:00:00.000000

"""

import json
import logging
import re

from alembic import op
from sqlalchemy import text

revision = "q7r8s9t0u1v2"
down_revision = "p6q7r8s9t0u1"
branch_labels = None
depends_on = None

log = logging.getLogger(__name__)


def _method_name(skill_name: str) -> str:
    # Same rule as utils.skills.skill_method_name, frozen for this migration.
    name = re.sub(r"[^A-Za-z0-9_]+", "_", (skill_name or "").strip())
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if not name:
        name = "skill"
    if name[0].isdigit():
        name = f"skill_{name}"
    return name


def _method_from_tool_id(tool_id: str):
    """Method part of a skill tool ID, or None when the ID has no clear one.

    IDs are skill_<method>, or skill_<repo>__<ref>[__<owner>]_<method> when
    the plain ID was taken. Methods have no hyphens, so in the second form
    the method starts after the first underscore following the last hyphen.
    """
    rest = tool_id[len("skill_") :]
    if "__" not in rest:
        return rest
    tail = rest.rsplit("__", 1)[1]
    if "-" in tail:
        after = tail.rsplit("-", 1)[1]
        if "_" in after:
            return after.split("_", 1)[1]
    return None


def convert_tool_ids(tool_ids, names_by_id, known_names):
    """(entries, skill IDs with no known name).

    Skill IDs become skill names; other tool IDs are kept. ``names_by_id``
    maps live skill tool IDs to their names. A stale ID is matched on its
    method part against ``known_names``.
    """
    by_method = {_method_name(name): name for name in known_names}
    entries, unmatched = [], []
    for tool_id in tool_ids:
        entry = names_by_id.get(tool_id)
        if entry is None and tool_id.startswith("skill_"):
            method = _method_from_tool_id(tool_id)
            if method is not None:
                entry = by_method.get(method) or by_method.get(
                    re.sub(r"_\d+$", "", method)
                )
            if entry is None:
                if tool_id not in unmatched:
                    unmatched.append(tool_id)
                continue
        entry = entry or tool_id
        if entry not in entries:
            entries.append(entry)
    return entries, unmatched


def _json(value):
    if value is None or isinstance(value, (list, dict)):
        return value
    return json.loads(value)


def upgrade():
    conn = op.get_bind()

    names_by_id = {}
    for tool_id, meta in conn.execute(text("SELECT id, meta FROM tool")).fetchall():
        manifest = (_json(meta) or {}).get("manifest") or {}
        if manifest.get("kind") == "skill" and manifest.get("skill_name"):
            names_by_id[tool_id] = manifest["skill_name"]
    known = set(names_by_id.values())
    for (meta,) in conn.execute(text("SELECT meta FROM skill_pack")).fetchall():
        for skill in (_json(meta) or {}).get("skills") or []:
            if isinstance(skill, dict) and skill.get("name"):
                known.add(skill["name"])

    rows = conn.execute(
        text("SELECT id, tool_ids FROM automation WHERE tool_ids IS NOT NULL")
    ).fetchall()
    for automation_id, raw in rows:
        tool_ids = [str(t) for t in (_json(raw) or []) if t]
        entries, unmatched = convert_tool_ids(tool_ids, names_by_id, known)
        if unmatched:
            log.warning(
                "automation %s: no skill name for %s", automation_id, unmatched
            )
        conn.execute(
            text("UPDATE automation SET tool_ids = :tool_ids WHERE id = :id"),
            {"tool_ids": json.dumps(entries), "id": automation_id},
        )


def downgrade():
    # The old skill IDs are not kept, so there is nothing to restore.
    pass
