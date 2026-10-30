"""Tool runner sizes: the catalog infra publishes, and each chat's chosen size.

Infra defines each size as a SandboxTemplate plus a warm pool of the same
name, labelled weather-skills.org/runner-type and annotated with what chat
shows and needs (charts/weather-skills-sandbox values.yaml `runners` in the
infrastructure repository). A chat runs on the default pool
(SKILL_K8S_SANDBOX_POOL) until it is switched to another size. A switched
size lasts while the chat uses it and ends when its runner would idle-stop,
so the next start is the default size again.

Kept in memory: the chat server runs one replica (charts/weather-skills-chat
replicaCount). A restart drops every choice, and the old size's claim then
idle-stops on its own.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

CATALOG_PREFIX = "weather-skills.org"
TYPE_LABEL = f"{CATALOG_PREFIX}/runner-type"
# On claims, so a chat's claims can be told apart by size.
CLAIM_TYPE_LABEL = "weather-skills-runner-type"


@dataclass(frozen=True)
class RunnerType:
    type: str
    name: str
    display_name: str
    description: str = ""
    order: int = 0
    warm: bool = True
    start_timeout_seconds: Optional[int] = None
    idle_ttl_seconds: Optional[int] = None
    requires_approval: bool = False
    cpus: Optional[float] = None
    memory_gib: Optional[float] = None

    def public(self) -> dict:
        return {
            "type": self.type,
            "display_name": self.display_name,
            "description": self.description,
            "warm": self.warm,
            "requires_approval": self.requires_approval,
            "cpus": self.cpus,
            "memory_gib": self.memory_gib,
            "idle_ttl_seconds": self.idle_ttl_seconds,
        }


def _int(value) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bool(value, default: bool) -> bool:
    raw = str(value or "").strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    return default


def from_template(
    template: dict, limits: Optional[tuple[float, float]]
) -> Optional[RunnerType]:
    """A RunnerType from a catalog SandboxTemplate, or None if it has no type label."""
    meta = template.get("metadata") or {}
    rtype = ((meta.get("labels") or {}).get(TYPE_LABEL) or "").strip()
    name = (meta.get("name") or "").strip()
    if not rtype or not name:
        return None
    ann = meta.get("annotations") or {}

    def note(key: str) -> Optional[str]:
        return ann.get(f"{CATALOG_PREFIX}/{key}")

    cpus, memory = limits if limits else (None, None)
    return RunnerType(
        type=rtype,
        name=name,
        display_name=(note("display-name") or rtype.title()).strip(),
        description=(note("description") or "").strip(),
        order=_int(note("order")) or 0,
        warm=_bool(note("warm"), True),
        start_timeout_seconds=_int(note("start-timeout-seconds")),
        idle_ttl_seconds=_int(note("idle-ttl-seconds")),
        requires_approval=_bool(note("requires-approval"), False),
        cpus=cpus,
        memory_gib=memory,
    )


def find(catalog: list[RunnerType], value: Optional[str]) -> Optional[RunnerType]:
    """The size named by its type or display name, ignoring case."""
    want = (value or "").strip().lower()
    if not want:
        return None
    for rtype in catalog:
        if want in (rtype.type.lower(), rtype.display_name.lower(), rtype.name.lower()):
            return rtype
    return None


def allowed_for_org(catalog: list[RunnerType], org) -> list[RunnerType]:
    """Sizes members of this organization may use.

    Sizes that need approval are for organizations a platform admin allowed
    (can_use_large_runners) and the platform organization.
    """
    big_ok = bool(
        org is not None
        and (getattr(org, "kind", None) == "platform" or getattr(org, "can_use_large_runners", False))
    )
    return [t for t in catalog if big_ok or not t.requires_approval]


_lock = threading.Lock()
# chat_id -> (size, monotonic time the choice ends)
_choices: dict[str, tuple[RunnerType, float]] = {}


def chosen(chat_id: Optional[str]) -> Optional[RunnerType]:
    """This chat's switched-to size, or None for the default pool."""
    if not chat_id:
        return None
    with _lock:
        hit = _choices.get(chat_id)
        if hit is None:
            return None
        rtype, until = hit
        if time.monotonic() >= until:
            _choices.pop(chat_id, None)
            return None
        return rtype


def choose(chat_id: str, rtype: Optional[RunnerType], seconds: float) -> None:
    """Switch the chat to rtype for at least `seconds`, or back to the default (None)."""
    with _lock:
        if rtype is None:
            _choices.pop(chat_id, None)
        else:
            _choices[chat_id] = (rtype, time.monotonic() + max(1.0, float(seconds)))


def keep(chat_id: str, rtype: Optional[RunnerType], seconds: float) -> None:
    """The chat used rtype: keep the choice at least `seconds` more.

    Only extends a choice of that same size; a chat that was switched since
    keeps its new choice.
    """
    if rtype is None:
        return
    with _lock:
        hit = _choices.get(chat_id)
        if hit is None or hit[0].name != rtype.name:
            return
        _choices[chat_id] = (rtype, max(hit[1], time.monotonic() + float(seconds)))


def same(a: Optional[RunnerType], b: Optional[RunnerType]) -> bool:
    return (a.name if a else None) == (b.name if b else None)
