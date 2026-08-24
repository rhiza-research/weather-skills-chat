"""Helpers for model-facing message content (vs UI serialization)."""

from __future__ import annotations

import html
import json
import re
from copy import deepcopy
from typing import Any, Optional
from uuid import uuid4

# Skill / tool result fields that are useful for the UI but not the model.
_INFRA_KEYS = frozenset({"cwd", "sandlock", "landlock_backend"})

# Cap noisy skill stdout/stderr so one tool cannot blow the context window.
_MAX_STREAM_CHARS = 12_000

_DETAILS_RE = re.compile(
    r'<details\s+type="(?:tool_calls|reasoning|code_interpreter)"[^>]*>.*?</details>',
    re.IGNORECASE | re.DOTALL,
)

_DETAILS_BLOCK_RE = re.compile(
    r"<details\s+([^>]*)>(.*?)</details>",
    re.IGNORECASE | re.DOTALL,
)

# Legacy client ``processDetails`` / model-echoed XML tool markup.
_LEGACY_TOOL_CALL_RE = re.compile(
    r"<tool_calls\s+([^>]*?)(?:\s*/>|>\s*)",
    re.IGNORECASE,
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


def _parse_html_attrs(attr_str: str) -> dict[str, str]:
    return dict(re.findall(r'(\w+)="([^"]*)"', attr_str or ""))


def _decode_attr_value(raw: Optional[str]) -> Any:
    """HTML-unescape a details attribute and JSON-decode when possible."""
    text = html.unescape(raw or "")
    if not text:
        return ""
    try:
        return json.loads(text)
    except Exception:
        return text


def _tool_arguments_string(value: Any) -> str:
    if value is None or value == "":
        return "{}"
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return "{}"
        # Already a JSON object/array string.
        if stripped[0] in "{[":
            return stripped
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                return json.dumps(parsed)
            if isinstance(parsed, str) and parsed.strip()[:1] in "{[":
                return parsed
        except Exception:
            pass
        return json.dumps({"_raw": value})
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return json.dumps(value)


def _segment_assistant_content(content: str) -> list[dict]:
    """Split UI assistant HTML into text / tool_calls segments (order preserved)."""
    segments: list[dict] = []

    def push_text(text: str):
        if not text:
            return
        text = re.sub(r"</?tool_calls\s*/?>", "", text, flags=re.IGNORECASE)
        if text.strip():
            segments.append({"type": "text", "content": text})

    def push_legacy_tools_from_text(text: str):
        if "<tool_calls" not in text:
            push_text(text)
            return
        cursor = 0
        for match in _LEGACY_TOOL_CALL_RE.finditer(text):
            push_text(text[cursor : match.start()])
            cursor = match.end()
            attrs = _parse_html_attrs(match.group(1))
            if attrs.get("name"):
                segments.append({"type": "tool_calls", "attrs": attrs})
        push_text(text[cursor:])

    pos = 0
    for match in _DETAILS_BLOCK_RE.finditer(content):
        push_legacy_tools_from_text(content[pos : match.start()])
        pos = match.end()
        attrs = _parse_html_attrs(match.group(1))
        dtype = (attrs.get("type") or "").lower()
        if dtype == "tool_calls":
            segments.append({"type": "tool_calls", "attrs": attrs})
        # reasoning / code_interpreter / unknown → omitted for the model
    push_legacy_tools_from_text(content[pos:])
    return segments


def expand_assistant_content_to_messages(content: str) -> list[dict]:
    """Convert UI-serialized assistant content into OpenAI assistant/tool messages.

    ``<details type="tool_calls">`` (and legacy ``<tool_calls>`` XML) become
    native ``tool_calls`` + ``role: tool`` turns. Reasoning/code_interpreter
    chrome is dropped.
    """
    if not isinstance(content, str):
        return []
    if not content.strip():
        return []

    needs_expand = (
        'type="tool_calls"' in content
        or 'type="reasoning"' in content
        or 'type="code_interpreter"' in content
        or "<tool_calls" in content
    )
    if not needs_expand:
        return [{"role": "assistant", "content": content}]

    segments = _segment_assistant_content(content)
    messages: list[dict] = []
    pending_text: list[str] = []
    idx = 0

    def flush_text_only():
        nonlocal pending_text
        text = "\n".join(part.strip() for part in pending_text if part.strip()).strip()
        pending_text = []
        if text:
            messages.append({"role": "assistant", "content": text})

    while idx < len(segments):
        segment = segments[idx]
        if segment["type"] == "text":
            pending_text.append(segment["content"])
            idx += 1
            continue

        # Gather consecutive tool_calls into one assistant turn.
        batch_attrs: list[dict] = []
        while idx < len(segments) and segments[idx]["type"] == "tool_calls":
            batch_attrs.append(segments[idx]["attrs"])
            idx += 1

        tool_calls = []
        tool_messages = []
        for attrs in batch_attrs:
            tool_id = attrs.get("id") or f"call_{uuid4().hex[:24]}"
            name = attrs.get("name") or "unknown"
            arguments = _tool_arguments_string(
                _decode_attr_value(attrs.get("arguments") or attrs.get("params"))
            )
            tool_calls.append(
                {
                    "id": tool_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            )
            result_raw = attrs.get("result")
            if result_raw is not None and result_raw != "":
                decoded = _decode_attr_value(result_raw)
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": compact_tool_result_for_model(decoded),
                    }
                )
            else:
                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": "",
                    }
                )

        text = "\n".join(part.strip() for part in pending_text if part.strip()).strip()
        pending_text = []
        messages.append(
            {
                "role": "assistant",
                "content": text or None,
                "tool_calls": tool_calls,
            }
        )
        messages.extend(tool_messages)

    flush_text_only()
    return messages


def expand_ui_tool_history_messages(messages: Optional[list[dict]]) -> list[dict]:
    """Expand UI ``<details type="tool_calls">`` history into native tool turns.

    Idempotent when messages are already OpenAI-native (assistant ``tool_calls``
    + ``role: tool``). Safe to run on every chat completion request.
    """
    out: list[dict] = []
    for message in messages or []:
        role = message.get("role")
        content = message.get("content")

        # Already-native tool turns pass through.
        if role == "tool" or message.get("tool_calls"):
            out.append(message)
            continue

        if role == "assistant" and isinstance(content, str):
            if (
                'type="tool_calls"' in content
                or 'type="reasoning"' in content
                or 'type="code_interpreter"' in content
                or "<tool_calls" in content
            ):
                expanded = expand_assistant_content_to_messages(content)
                if expanded:
                    out.extend(expanded)
                    continue

        out.append(message)
    return out
