"""Send skill tools on demand: each is marked ``defer_loading`` and found with
``skill_search`` (OpenRouter tool deferral).

A deferred tool is loaded from the next model call once ``skill_search`` has
returned it or the conversation has called it, and stays loaded for the chat.
"""

import json
import re

SKILL_SEARCH = "skill_search"
SEARCH_RESULTS = 5

SKILL_SEARCH_SPEC = {
    "name": SKILL_SEARCH,
    "description": (
        "Load skills before calling them. Every skill this chat has is named in "
        "the system prompt; call this with words from what you need, and the best "
        "matches can be called from your next step."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Skill names or words, e.g. 'standardized anomaly' or 'imerg chirps'",
            }
        },
        "required": ["query"],
    },
}


def add_skill_search(tools_dict: dict) -> set[str]:
    """Add ``skill_search`` to the chat's tools; return the names it can load."""
    deferred = {
        name
        for name, tool in tools_dict.items()
        if tool.get("tool_id") and not tool.get("direct")
    }
    if not deferred:
        return deferred

    async def skill_search(query: str = "", **_ignored) -> str:
        terms = set(re.findall(r"[a-z0-9]+", (query or "").lower()))
        scored = []
        for name in deferred:
            text = f"{name} {tools_dict[name]['spec'].get('description') or ''}".lower()
            score = sum(2 * (t in name) + (t in text) for t in terms)
            if score:
                scored.append((-score, name))
        found = [name for _, name in sorted(scored)[:SEARCH_RESULTS]]
        return json.dumps({"found": found})

    tools_dict[SKILL_SEARCH] = {
        "toolkit_id": "builtin",
        "callable": skill_search,
        "spec": SKILL_SEARCH_SPEC,
        "pydantic_model": None,
        "file_handler": False,
        "citation": False,
    }
    return deferred


def defer_tools(tools: list[dict], deferred: set[str]) -> list[dict]:
    """Mark the ``deferred`` tools in an OpenAI ``tools`` list."""
    return [
        {**t, "function": {**t["function"], "defer_loading": True}}
        if t.get("function", {}).get("name") in deferred
        else t
        for t in tools
    ]


def _loaded_names(messages: list) -> set[str]:
    """Tools the conversation has called, and those ``skill_search`` found."""
    names, search_ids = set(), set()
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        for call in msg.get("tool_calls") or []:
            name = (call.get("function") or {}).get("name")
            names.add(name)
            if name == SKILL_SEARCH:
                search_ids.add(call.get("id"))
        if msg.get("role") == "tool" and msg.get("tool_call_id") in search_ids:
            try:
                names.update(json.loads(msg.get("content") or "{}").get("found") or [])
            except (TypeError, ValueError, AttributeError):
                pass
    return names


def apply_deferred_tools(payload: dict, defer: bool) -> dict:
    """Load the deferred tools the conversation found, and send the rest last.

    Only OpenRouter takes ``defer_loading``; elsewhere (``defer`` false) every
    tool is sent in full. Deferred tools go last so the cache breakpoint on the
    last loaded tool stays put.
    """
    tools = payload.get("tools")
    if not isinstance(tools, list) or not any(
        (t.get("function") or {}).get("defer_loading") for t in tools if isinstance(t, dict)
    ):
        return payload
    loaded = _loaded_names(payload.get("messages")) if defer else None
    out_loaded, out_deferred = [], []
    for t in tools:
        fn = t.get("function") or {}
        if fn.get("defer_loading") and (loaded is None or fn.get("name") in loaded):
            t = {**t, "function": {k: v for k, v in fn.items() if k != "defer_loading"}}
        (out_deferred if t.get("function", {}).get("defer_loading") else out_loaded).append(t)
    return {**payload, "tools": out_loaded + out_deferred}
