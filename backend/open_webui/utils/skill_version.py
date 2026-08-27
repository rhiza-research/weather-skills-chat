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


def resolve_tool_ids_by_skill_version(
    tool_ids: list[str],
    skills: list[dict],
) -> list[str]:
    """Replace enabled skill tool IDs with a same-named higher-version copy.

    ``skills`` items are ``{id, skill_name, version, enabled?}`` records the
    user can access. Equal versions keep the originally requested tool.
    Unknown IDs (builtin servers, missing rows) pass through unchanged.

    Globally disabled skills (``enabled is False``) are never chosen as an
    upgrade target. If the user explicitly selected a disabled skill ID, that
    ID is kept as-is so the chat bar can still opt in.
    """
    by_id = {s["id"]: s for s in skills if s.get("id")}
    best_by_name: dict[str, dict] = {}
    for skill in skills:
        if skill.get("enabled") is False:
            continue
        name = skill.get("skill_name")
        if not name:
            continue
        current = best_by_name.get(name)
        if current is None or prefer_incoming_tool_version(
            skill.get("version"), current.get("version")
        ):
            best_by_name[name] = skill

    resolved: list[str] = []
    seen: set[str] = set()
    for tool_id in tool_ids:
        skill = by_id.get(tool_id)
        if skill and skill.get("enabled") is not False:
            best = best_by_name.get(skill.get("skill_name") or "")
            if best and prefer_incoming_tool_version(
                best.get("version"), skill.get("version")
            ):
                log.info(
                    "Using %s@%s instead of %s@%s for skill %s",
                    best.get("id"),
                    best.get("version"),
                    tool_id,
                    skill.get("version"),
                    skill.get("skill_name"),
                )
                tool_id = best["id"]
        if tool_id in seen:
            continue
        seen.add(tool_id)
        resolved.append(tool_id)
    return resolved


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
