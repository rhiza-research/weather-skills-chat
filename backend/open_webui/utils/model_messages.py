"""Helpers for model-facing message content (vs UI serialization)."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any, Optional

# Skill / tool result fields that are useful for the UI but not the model.
_INFRA_KEYS = frozenset({"cwd", "sandlock", "landlock_backend"})

# Cap noisy skill stdout/stderr so one tool cannot blow the context window.
_MAX_STREAM_CHARS = 12_000

_DETAILS_RE = re.compile(
    r'<details\s+type="(?:tool_calls|reasoning|code_interpreter)"[^>]*>.*?</details>',
    re.IGNORECASE | re.DOTALL,
)


def strip_message_details_for_tasks(messages: Optional[list[dict]]) -> list[dict]:
    """Copy messages with UI ``<details>`` blocks removed for title/tag tasks."""
    out: list[dict] = []
    for message in messages or []:
        copied = dict(message)
        content = copied.get("content")
        if isinstance(content, str):
            content = _DETAILS_RE.sub("", content)
            content = re.sub(r"\n{3,}", "\n\n", content).strip()
            copied["content"] = content
        out.append(copied)
    return out


def serialize_content_blocks_for_model(content_blocks: list[dict]) -> str:
    """Plain text from content blocks — no UI ``<details>`` chrome."""
    parts: list[str] = []
    for block in content_blocks or []:
        btype = block.get("type")
        if btype in ("text", "reasoning", "solution"):
            text = (block.get("content") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def _truncate_stream(text: str, limit: int = _MAX_STREAM_CHARS) -> str:
    if not isinstance(text, str) or len(text) <= limit:
        return text
    omitted = len(text) - limit
    return text[:limit] + f"\n...[truncated {omitted} chars]"


def _compact_skill_dict(data: dict) -> dict:
    compact = {
        k: v for k, v in data.items() if k not in _INFRA_KEYS and k != "stderr"
    }
    ok = data.get("ok")
    exit_code = data.get("exit_code")
    success = ok is True or (ok is None and exit_code == 0)

    if not success:
        if "stderr" in data:
            compact["stderr"] = data["stderr"]
        # Preserve ok/exit_code for failures even if filtered above
        if "ok" in data:
            compact["ok"] = data["ok"]
        if "exit_code" in data:
            compact["exit_code"] = data["exit_code"]

    for key in ("stdout", "stderr"):
        if key in compact and isinstance(compact[key], str):
            compact[key] = _truncate_stream(compact[key])

    return compact


def _looks_like_skill_result(data: dict) -> bool:
    return any(k in data for k in ("ok", "exit_code", "stdout", "stderr", "script"))


def compact_tool_result_for_model(content: Any) -> str:
    """Shrink tool result strings sent as ``role: tool`` content.

    Success skill results drop stderr and sandbox infra. Failures keep stderr.
    Long streams are truncated. Non-skill payloads get a length cap only.
    """
    if content is None:
        return ""

    if isinstance(content, (dict, list)):
        raw = content
        text = None
    elif isinstance(content, str):
        text = content
        raw = None
        stripped = content.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                raw = json.loads(stripped)
            except Exception:
                raw = None
    else:
        return _truncate_stream(str(content))

    if isinstance(raw, dict) and _looks_like_skill_result(raw):
        return json.dumps(_compact_skill_dict(raw), indent=2)

    if isinstance(raw, (dict, list)):
        encoded = json.dumps(raw, indent=2)
        return _truncate_stream(encoded, limit=_MAX_STREAM_CHARS * 2)

    if text is None:
        return ""
    return _truncate_stream(text, limit=_MAX_STREAM_CHARS * 2)


def deepcopy_messages(messages: list[dict]) -> list[dict]:
    """Deep-copy chat messages so upstream transforms cannot mutate the loop."""
    return deepcopy(messages or [])
