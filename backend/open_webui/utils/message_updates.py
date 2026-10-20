"""Merge rules for the parts of a reply that arrive as separate socket events.

The server saves these itself; the browser applies the same rules to its live
copy (src/lib/chat/cache.ts), so a reloaded reply matches what was streamed.

- status: only the latest is kept, as a one-item ``statusHistory`` list.
- usage: token and cost numbers are added up across the model calls of a reply.
- sources: appended.
- code_executions: replaced by ``id``, new ones appended.
- files: appended, without repeating a file already listed.
"""

import copy
import json
import math
import re
from typing import Any, Optional

# Same rule as accumulateUsage in src/lib/utils/usage.ts.
_SUMMABLE_KEY = re.compile(r"token|cost", re.IGNORECASE)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def accumulate_usage(existing: Any, incoming: Any) -> Any:
    """Add one usage report to the running total for a reply.

    Numeric token and cost fields, including nested ones, are summed. Other
    fields keep the latest value.
    """
    if incoming is None:
        return existing
    if existing is None:
        return copy.deepcopy(incoming)
    if _is_number(incoming):
        return (existing if _is_number(existing) else 0) + incoming
    if not isinstance(incoming, dict):
        return copy.deepcopy(incoming)
    out = dict(existing) if isinstance(existing, dict) else {}
    for key, value in incoming.items():
        if isinstance(value, dict):
            out[key] = accumulate_usage(out.get(key), value)
        elif _is_number(value) and _SUMMABLE_KEY.search(str(key)):
            previous = out.get(key)
            out[key] = (previous if _is_number(previous) else 0) + value
        else:
            out[key] = copy.deepcopy(value)
    return out


def _file_key(item: Any) -> str:
    if isinstance(item, dict):
        for field in ("url", "id"):
            if item.get(field):
                return f"{field}:{item[field]}"
    return "json:" + json.dumps(item, sort_keys=True, default=str)


def merge_files(existing: Optional[list], incoming: Optional[list]) -> list:
    merged = list(existing or [])
    seen = {_file_key(item) for item in merged}
    for item in incoming or []:
        key = _file_key(item)
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


def upsert_by_id(existing: Optional[list], incoming: Optional[list]) -> list:
    merged = list(existing or [])
    for item in incoming or []:
        item_id = item.get("id") if isinstance(item, dict) else None
        index = next(
            (
                position
                for position, current in enumerate(merged)
                if item_id is not None
                and isinstance(current, dict)
                and current.get("id") == item_id
            ),
            None,
        )
        if index is None:
            merged.append(item)
        else:
            merged[index] = item
    return merged


def add_to_pending(pending: dict, kind: str, data: Any) -> None:
    """Fold one event into the batch waiting to be written."""
    if kind == "status":
        pending["status"] = data
    elif kind == "usage":
        pending["usage"] = accumulate_usage(pending.get("usage"), data)
    elif kind == "source":
        pending.setdefault("sources", []).append(data)
    elif kind == "code_execution":
        pending["code_executions"] = upsert_by_id(
            pending.get("code_executions"), [data]
        )
    elif kind == "files":
        pending["files"] = merge_files(pending.get("files"), data)


def apply_to_message(message: dict, updates: dict) -> dict:
    """The stored message with a written batch merged in."""
    merged = dict(message)
    if "status" in updates:
        # Screens show the last entry of statusHistory; a one-item list keeps
        # them and older chats working.
        merged["statusHistory"] = [updates["status"]]
    if updates.get("usage") is not None:
        merged["usage"] = accumulate_usage(merged.get("usage"), updates["usage"])
    if updates.get("sources"):
        merged["sources"] = [*(merged.get("sources") or []), *updates["sources"]]
    if updates.get("code_executions"):
        merged["code_executions"] = upsert_by_id(
            merged.get("code_executions"), updates["code_executions"]
        )
    if updates.get("files"):
        merged["files"] = merge_files(merged.get("files"), updates["files"])
    return merged
