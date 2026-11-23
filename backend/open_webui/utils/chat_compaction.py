"""Compact a chat: a model summary replaces its earlier messages for the model.

The summary is saved on the assistant message where the chat was compacted,
as ``compaction``. ``chat_turns.messages_for_model`` leaves out everything up
to it. The person still sees every message.
"""

import asyncio
import json
import logging
import time
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.chats import Chats
from open_webui.utils.chat_turns import (
    _append_note,
    compaction_note,
    messages_for_model,
    prepend_note,
)
from open_webui.utils.model_messages import expand_ui_tool_history_messages

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

# The page treats a compaction still running after this long as failed.
COMPACTION_TIMEOUT_S = 90
END_OF_TURN_RATIO = 0.9
CHARS_PER_TOKEN = 4


def compaction_running(compaction, now: Optional[float] = None) -> bool:
    """A compaction still running; one older than the timeout died with its server."""
    if not isinstance(compaction, dict) or compaction.get("status") != "running":
        return False
    started = compaction.get("started_at")
    if not isinstance(started, (int, float)):
        return False
    return (now if now is not None else time.time()) - started < COMPACTION_TIMEOUT_S

SUMMARY_INSTRUCTIONS = """Summarize the conversation below. The summary replaces it: the assistant will continue the conversation with only the summary as context, so keep everything needed to carry on.

Include:
- What the user wants and asked for, and any preferences they stated.
- Decisions and conclusions reached.
- Datasets, regions, dates, variables, models and parameters used.
- Files and artifacts created or read, with their exact paths.
- Results of tool calls that later work may need, with key numbers.
- Errors met and how they were resolved.
- Open questions and what was about to happen next.

Write plain notes. No preamble."""

TOOL_RESULT_REMOVED = (
    "[This tool result was removed to fit the model's context window. "
    "Run the tool again if you need it.]"
)


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                parts.append(part.get("text") or "")
            elif part.get("type") == "image_url":
                parts.append("[image]")
        return "\n".join(parts)
    return ""


def message_chars(messages: list[dict]) -> int:
    """Characters of the text a model call sends, for estimating its tokens."""
    total = 0
    for message in messages or []:
        total += len(_text(message.get("content")))
        if message.get("tool_calls"):
            total += len(json.dumps(message["tool_calls"]))
    return total


def transcript_text(messages: list[dict]) -> str:
    """The conversation as one text, so the summary call sends no tool turns."""
    lines = []
    for message in expand_ui_tool_history_messages(messages):
        role = message.get("role")
        text = _text(message.get("content")).strip()
        if role == "tool":
            lines.append(f"TOOL RESULT:\n{text}")
            continue
        if text:
            lines.append(f"{str(role).upper()}:\n{text}")
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            lines.append(
                f"ASSISTANT CALLED {function.get('name')}: {function.get('arguments') or ''}"
            )
    return "\n\n".join(lines)


def summary_request(messages: list[dict]) -> str:
    return (
        f"{SUMMARY_INSTRUCTIONS}\n\n<conversation>\n"
        f"{transcript_text(messages)}\n</conversation>"
    )


def compaction_estimate(usage, summary_usage) -> dict:
    """Context use after compacting, from the reply's usage and the summary call's.

    The summary call's prompt is the removed transcript plus the instructions;
    its completion is the summary that replaces it.
    """
    usage = usage if isinstance(usage, dict) else {}
    summary_usage = summary_usage if isinstance(summary_usage, dict) else {}
    used = usage.get("context_used")
    window = usage.get("context_window")
    removed = summary_usage.get("prompt_tokens")
    added = summary_usage.get("completion_tokens")
    if not all(isinstance(v, (int, float)) for v in (used, window, removed, added)):
        return {}
    removed -= len(SUMMARY_INSTRUCTIONS) // CHARS_PER_TOKEN
    estimate = max(int(used - max(0, removed) + added), int(added))
    return {"context_estimate": estimate, "context_window": window}


async def _emit(emitter_meta: dict, chat_id: str, message_id: str, data: dict):
    from open_webui.socket.main import get_event_emitter

    emitter = get_event_emitter(
        {**emitter_meta, "chat_id": chat_id, "message_id": message_id},
        update_db=False,
    )
    try:
        await emitter({"type": "chat:compaction", "data": data})
    except Exception:
        log.debug("compaction event failed chat_id=%s", chat_id, exc_info=True)


async def _summarize(request, user, model_id: str, prompt: str, metadata: dict):
    from open_webui.utils.chat import generate_chat_completion
    from open_webui.utils.models import remember_catalog_model

    # A server that has not served this model since it started has not loaded it.
    await asyncio.to_thread(remember_catalog_model, request, model_id)
    response = await generate_chat_completion(
        request,
        {
            "model": model_id,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "metadata": metadata,
        },
        user,
    )
    if not isinstance(response, dict):
        raise ValueError("The summary call returned no reply")
    choices = response.get("choices") or []
    summary = ((choices[0] if choices else {}).get("message") or {}).get("content")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("The summary call returned no text")
    return summary.strip(), response.get("usage")


async def compact_chat(
    request,
    user,
    *,
    chat_id: str,
    message_id: str,
    model_id: str,
    emitter_meta: dict,
    organization_id: Optional[str] = None,
    usage: Optional[dict] = None,
    message_map: Optional[dict] = None,
) -> Optional[dict]:
    """Summarize the chat up to and including message_id and save it there.

    Returns the saved compaction, or ``{"status": "failed"}`` or
    ``{"status": "cancelled"}`` when a new turn was added to that message
    meanwhile. At the end of a turn the reply's final
    text and usage may not be saved yet, so the caller passes them as
    message_map and usage.
    """
    chat = await asyncio.to_thread(Chats.get_chat_by_id, chat_id)
    document = dict(chat.chat) if chat else {}
    history = document.get("history") or {}
    message = (history.get("messages") or {}).get(message_id)
    if not isinstance(message, dict):
        return {"status": "failed"}
    children = list(message.get("childrenIds") or [])
    if message_map:
        document["history"] = {**history, "messages": message_map}

    running = {"status": "running", "started_at": int(time.time())}
    await asyncio.to_thread(
        Chats.set_message_compaction,
        chat_id,
        message_id,
        running,
        bump_revision=False,
    )
    await _emit(emitter_meta, chat_id, message_id, running)

    compaction = None
    outcome = "failed"
    try:
        prompt = summary_request(messages_for_model(document, message_id))
        summary, summary_usage = await asyncio.wait_for(
            _summarize(
                request,
                user,
                model_id,
                prompt,
                {
                    "task": "chat_compaction",
                    "chat_id": chat_id,
                    "user_id": user.id,
                    "organization_id": organization_id,
                },
            ),
            COMPACTION_TIMEOUT_S,
        )
        done = {
            "status": "done",
            "summary": summary,
            "model": model_id,
            "created_at": int(time.time()),
            **compaction_estimate(usage or message.get("usage"), summary_usage),
        }
        if await asyncio.to_thread(
            Chats.set_message_compaction,
            chat_id,
            message_id,
            done,
            children=children,
        ):
            compaction = done
        else:
            outcome = "cancelled"
    except Exception:
        log.warning("Chat compaction failed chat_id=%s", chat_id, exc_info=True)

    if compaction is None:
        try:
            await asyncio.to_thread(
                Chats.set_message_compaction, chat_id, message_id, None
            )
        except Exception:
            log.warning("Could not clear compaction chat_id=%s", chat_id, exc_info=True)
    result = compaction or {"status": outcome}
    await _emit(emitter_meta, chat_id, message_id, result)
    return result


def compacted_messages(messages: list[dict], summary: str, notes: str) -> list[dict]:
    """The call's messages after compacting everything before this turn.

    Keeps the leading system messages and the turn from its user message on;
    the summary and the chat's notes move onto that user message.
    """
    last_user = max(
        (i for i, m in enumerate(messages) if m.get("role") == "user"), default=None
    )
    if last_user is None:
        return messages
    head = [m for m in messages[:last_user] if m.get("role") == "system"]
    current = dict(messages[last_user])
    content = _append_note(current.get("content"), notes)
    current["content"] = prepend_note(content, compaction_note(summary))
    return [*head, current, *messages[last_user + 1 :]]


def _estimate(messages, used_before, chars_before) -> int:
    chars = message_chars(messages)
    if used_before is None:
        return chars // CHARS_PER_TOKEN
    return int(used_before + (chars - chars_before) // CHARS_PER_TOKEN)


def _drop_old_tool_results(messages, used_before, chars_before, window) -> list[dict]:
    """Replace the oldest tool results with a note until the call fits."""
    excess = (_estimate(messages, used_before, chars_before) - window) * CHARS_PER_TOKEN
    out = list(messages)
    for index, message in enumerate(out):
        if excess <= 0:
            break
        if message.get("role") == "tool" and message.get("content") != TOOL_RESULT_REMOVED:
            excess -= len(_text(message.get("content"))) - len(TOOL_RESULT_REMOVED)
            out[index] = {**message, "content": TOOL_RESULT_REMOVED}
    return out


async def fit_model_call(
    request,
    user,
    model: dict,
    metadata: dict,
    base: list[dict],
    call: list[dict],
    used_before: Optional[int],
    chars_before: int,
) -> tuple[list[dict], list[dict]]:
    """Before a model call, make it fit the model's context window.

    base is the turn's messages before this turn's tool calls; call is what
    the model gets. used_before is the prompt tokens of the turn's previous
    call (or the context the previous reply ended at) and chars_before the
    characters it was counted for; None estimates the whole call from its
    characters. Over the window, the chat is compacted up to the reply this
    turn follows, once per turn; then the oldest tool results are dropped
    from the call. Returns the new base and call.
    """
    try:
        return await _fit_model_call(
            request, user, model, metadata, base, call, used_before, chars_before
        )
    except Exception:
        # Sending the call as it was is no worse than before this check.
        log.warning("Fitting a model call failed", exc_info=True)
        return base, call


async def _fit_model_call(
    request, user, model, metadata, base, call, used_before, chars_before
):
    from open_webui.routers.openai import context_window_for

    if not (model or {}).get("id"):
        return base, call
    window = await context_window_for(request, user, model["id"])
    if not window or _estimate(call, used_before, chars_before) <= window:
        return base, call

    state = metadata.get("compaction")
    parent = (state or {}).get("parent") or {}
    if (
        state
        and not state.get("done")
        and parent.get("id")
        and (parent.get("compaction") or {}).get("status") != "done"
        and not compaction_running(parent.get("compaction"))
    ):
        state["done"] = True
        compaction = await compact_chat(
            request,
            user,
            chat_id=metadata["chat_id"],
            message_id=parent["id"],
            model_id=model["id"],
            emitter_meta=metadata,
            organization_id=metadata.get("organization_id"),
        )
        if compaction["status"] == "done":
            chat = await asyncio.to_thread(Chats.get_chat_by_id, metadata["chat_id"])
            notes = "\n\n".join(
                n for n in ((chat.chat if chat else {}).get("chatNotes") or []) if n
            )
            new_base = compacted_messages(base, compaction["summary"], notes)
            # The estimate falls by the characters the summary replaced.
            call = [*new_base, *call[len(base) :]]
            base = new_base

    return base, _drop_old_tool_results(call, used_before, chars_before, window)


async def fit_first_call(
    request, user, model: dict, metadata: dict, messages: list[dict]
) -> list[dict]:
    """fit_model_call for a turn's first call, estimated from the previous reply.

    That reply's context use covers everything but the new user message.
    """
    parent = ((metadata.get("compaction") or {}).get("parent")) or {}
    used = (parent.get("usage") or {}).get("context_used")
    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    chars_before = message_chars(messages) - message_chars([last_user] if last_user else [])
    _, call = await fit_model_call(
        request, user, model, metadata, messages, messages, used, chars_before
    )
    return call


async def compact_at_turn_end(
    request, user, model: dict, metadata: dict, usage: Optional[dict], message_map: dict
) -> None:
    """After a turn, compact at its reply when the context is over 90% full."""
    state = metadata.get("compaction")
    if not state or state.get("done") or not isinstance(usage, dict):
        return
    used, window = usage.get("context_used"), usage.get("context_window")
    if not used or not window or used <= END_OF_TURN_RATIO * window:
        return
    state["done"] = True
    await compact_chat(
        request,
        user,
        chat_id=metadata["chat_id"],
        message_id=metadata["message_id"],
        model_id=(model or {}).get("id"),
        emitter_meta=metadata,
        organization_id=metadata.get("organization_id"),
        usage=usage,
        message_map=message_map,
    )
