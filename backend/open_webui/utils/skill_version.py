"""Prefer the higher version when two skills share a function name."""

from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)


def parse_tool_version(value) -> tuple[tuple[int, ...], int, str] | None:
    """Parse a skill/tool version for comparison.

    Returns a sortable tuple, or None if ``value`` is missing/unparseable.
    Pre-release suffixes (``-dev``, ``-rc1``, …) sort below the same numeric
    version without a suffix.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text[0] in "vV" and len(text) > 1 and text[1].isdigit():
        text = text[1:]
    main, _, pre = text.partition("-")
    main, _, _build = main.partition("+")
    parts: list[int] = []
    for piece in main.split("."):
        if piece.isdigit():
            parts.append(int(piece))
            continue
        match = re.match(r"^(\d+)", piece)
        if match:
            parts.append(int(match.group(1)))
            break
        break
    if not parts:
        return None
    # Pad so 0.1 and 0.1.0 compare equal; extra segments still win (0.1.10).
    padded = tuple(parts + [0] * max(0, 4 - len(parts)))
    # (numeric parts, is_release, pre) so 1.0 > 1.0-rc
    return (padded, 0 if pre else 1, pre.lower())


def tool_version_from_record(tool) -> str | None:
    """Read a skill version from a Tools DB row, if present."""
    if tool is None:
        return None
    meta = getattr(tool, "meta", None)
    if meta is None:
        return None
    manifest = getattr(meta, "manifest", None)
    if manifest is None and isinstance(meta, dict):
        manifest = meta.get("manifest")
    if isinstance(manifest, dict):
        version = manifest.get("version")
        if version is not None and str(version).strip():
            return str(version)
    return None


def prefer_incoming_tool_version(incoming, existing) -> bool:
    """True when ``incoming`` should replace ``existing`` on a name collision."""
    incoming_parsed = parse_tool_version(incoming)
    existing_parsed = parse_tool_version(existing)
    if incoming_parsed is None:
        return False
    if existing_parsed is None:
        return True
    return incoming_parsed > existing_parsed


def newest_skill_per_name(skills: list[dict]) -> dict[str, dict]:
    """The highest-version record for each skill name.

    ``skills`` items are ``{id, skill_name, version}`` records the user can
    use. On equal versions the first record wins.
    """
    newest: dict[str, dict] = {}
    for skill in skills:
        name = skill.get("skill_name")
        if not name:
            continue
        current = newest.get(name)
        if current is None or prefer_incoming_tool_version(
            skill.get("version"), current.get("version")
        ):
            newest[name] = skill
    return newest


def resolve_tool_selection(entries: list[str], skills: list[dict]) -> list[str]:
    """Tool IDs to offer for a selection of skill names and tool IDs.

    A skill name becomes its newest copy in ``skills``. A skill ID becomes a
    same-named copy with a higher version, if there is one. Other tool IDs,
    and names with no copy, pass through unchanged.
    """
    by_id = {s["id"]: s for s in skills if s.get("id")}
    newest = newest_skill_per_name(skills)

    resolved: list[str] = []
    for entry in entries:
        tool_id = entry
        if entry in newest:
            tool_id = newest[entry]["id"]
        elif entry in by_id:
            skill = by_id[entry]
            best = newest.get(skill.get("skill_name") or "")
            if best and prefer_incoming_tool_version(
                best.get("version"), skill.get("version")
            ):
                log.info(
                    "Using %s@%s instead of %s@%s for skill %s",
                    best.get("id"),
                    best.get("version"),
                    entry,
                    skill.get("version"),
                    skill.get("skill_name"),
                )
                tool_id = best["id"]
        if tool_id not in resolved:
            resolved.append(tool_id)
    return resolved


def tool_ids_with_skill_names(tool_ids: list[str], catalog: list) -> list[str]:
    """Replace skill tool IDs with skill names, so a later run can use the
    newest copy. Other tool IDs, and entries not in ``catalog``, are kept."""
    names_by_id = {}
    for tool in catalog:
        manifest = (tool.meta.manifest if tool.meta else None) or {}
        if manifest.get("kind") == "skill" and manifest.get("skill_name"):
            names_by_id[tool.id] = manifest["skill_name"]
    entries: list[str] = []
    for tool_id in tool_ids:
        entry = names_by_id.get(tool_id, tool_id)
        if entry not in entries:
            entries.append(entry)
    return entries


def register_tool_by_function_name(
    tools_dict: dict[str, dict],
    function_name: str,
    tool_dict: dict,
) -> None:
    """Insert ``tool_dict`` under ``function_name``, keeping the higher version."""
    existing = tools_dict.get(function_name)
    if existing is None:
        tools_dict[function_name] = tool_dict
        return

    incoming_id = tool_dict.get("tool_id")
    existing_id = existing.get("tool_id")
    incoming_ver = tool_dict.get("version")
    existing_ver = existing.get("version")
    if prefer_incoming_tool_version(incoming_ver, existing_ver):
        log.info(
            "Preferring %s.%s@%s over %s@%s (higher version)",
            incoming_id,
            function_name,
            incoming_ver,
            existing_id,
            existing_ver,
        )
        tools_dict[function_name] = tool_dict
    else:
        log.warning("Tool %s already exists in another tools!", function_name)
        log.warning("Discarding %s.%s", incoming_id, function_name)
