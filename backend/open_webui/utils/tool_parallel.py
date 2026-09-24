"""Schedule same-turn tool calls: parallel by default, serial via depends_on."""

from __future__ import annotations

from typing import Any, Iterable

DEPENDS_ON_PARAM = "depends_on"
DISPLAY_PARAM = "display"

DEPENDS_ON_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "description": (
        "Optional. Function names or tool_call ids in this same turn that must "
        "finish before this call starts. Omit to run in parallel with sibling calls. "
        "If this call needs another call's output, either set depends_on or wait "
        "and invoke it in a later turn."
    ),
}


DISPLAY_SCHEMA = {
    "type": "string",
    "description": (
        "Optional. A short phrase shown to the user instead of the function name "
        'while this call runs, such as "Checking the most recent available date '
        'for IMERG" or "Grouping the data into weekly bins". Omit to show the '
        "function name."
    ),
}


def _ensure_parameter_properties(spec: dict | None) -> dict:
    spec = spec if isinstance(spec, dict) else {}
    params = spec.setdefault("parameters", {})
    if not isinstance(params, dict):
        spec["parameters"] = params = {"type": "object", "properties": {}}
    props = params.setdefault("properties", {})
    if not isinstance(props, dict):
        params["properties"] = props = {}
    return props


def inject_depends_on_spec(spec: dict | None) -> dict:
    """Add reserved depends_on and display parameters to a function spec."""
    spec = spec if isinstance(spec, dict) else {}
    props = _ensure_parameter_properties(spec)
    props.setdefault(DEPENDS_ON_PARAM, dict(DEPENDS_ON_SCHEMA))
    props.setdefault(DISPLAY_PARAM, dict(DISPLAY_SCHEMA))
    return spec


def parse_depends_on(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def strip_depends_on(params: dict | None) -> tuple[dict, list[str]]:
    cleaned = dict(params or {})
    deps = parse_depends_on(cleaned.pop(DEPENDS_ON_PARAM, None))
    return cleaned, deps


def strip_display(params: dict | None) -> dict:
    """Drop the reserved display phrase before a tool function runs."""
    cleaned = dict(params or {})
    cleaned.pop(DISPLAY_PARAM, None)
    return cleaned


def execution_waves(
    call_ids: list[str],
    names: list[str],
    depends_on: list[list[str]],
) -> list[list[int]]:
    """Partition same-turn calls into waves.

    A call may depend on sibling tool_call ids or function names. Dependencies
    that are not in this batch are treated as already satisfied (prior turn).
    Cycles fall back to a single remaining wave (best-effort parallel).
    """
    n = len(call_ids)
    if n == 0:
        return []
    if n != len(names) or n != len(depends_on):
        raise ValueError("call_ids, names, and depends_on must be the same length")

    id_to_idx = {cid: i for i, cid in enumerate(call_ids) if cid}
    name_to_idxs: dict[str, list[int]] = {}
    for i, name in enumerate(names):
        if name:
            name_to_idxs.setdefault(name, []).append(i)

    pred: list[set[int]] = [set() for _ in range(n)]
    for i, deps in enumerate(depends_on):
        for dep in deps:
            if dep in id_to_idx:
                j = id_to_idx[dep]
                if j != i:
                    pred[i].add(j)
                continue
            for j in name_to_idxs.get(dep, []):
                if j != i:
                    pred[i].add(j)

    remaining = set(range(n))
    completed: set[int] = set()
    waves: list[list[int]] = []

    while remaining:
        wave = sorted(i for i in remaining if pred[i].issubset(completed))
        if not wave:
            # Cycle or unsatisfiable edge — run the rest together.
            waves.append(sorted(remaining))
            break
        waves.append(wave)
        remaining.difference_update(wave)
        completed.update(wave)

    return waves
