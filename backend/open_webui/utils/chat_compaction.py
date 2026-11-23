"""Compact a chat: a model summary replaces its earlier messages for the model.

The summary is saved on the assistant message where the chat was compacted,
as ``compaction``. ``chat_turns.messages_for_model`` leaves out everything up
to it. The person still sees every message.

The summary call reads the chat's prompt cache when that is cheaper than
sending the conversation fresh: it extends the chat's last cached request, or
during a reply the turn's own request. Otherwise it sends the conversation as
one text, without the system prompt and tools.
"""

import asyncio
import json
import logging
import time
from typing import NamedTuple, Optional

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
SUMMARY_MAX_TOKENS = 16000


def compaction_running(compaction, now: Optional[float] = None) -> bool:
    """A compaction still running; one older than the timeout died with its server."""
    if not isinstance(compaction, dict) or compaction.get("status") != "running":
        return False
    started = compaction.get("started_at")
    if not isinstance(started, (int, float)):
        return False
    return (now if now is not None else time.time()) - started < COMPACTION_TIMEOUT_S

SUMMARY_INSTRUCTIONS = """Summarize this conversation. The summary replaces it: the assistant will continue the conversation with only the summary as context, so keep everything needed to carry on.

Include:
- What the user wants and asked for, and any preferences they stated.
- Decisions and conclusions reached.
- Datasets, regions, dates, variables, models and parameters used.
- Files and artifacts created or read, with their exact paths.
- Results of tool calls that later work may need, with key numbers.
- Errors met and how they were resolved.
- Open questions and what was about to happen next.

Write plain notes. No preamble.

Many parts of the chat can likely be made concise by describing the final result of a set of analysis and/or tool calls. Please be as concise as reasonably possible without preventing continued analysis."""

# For a summary call that keeps the chat's tools so it can read the cache.
CACHED_INSTRUCTIONS = (
    f"{SUMMARY_INSTRUCTIONS}\n\nAnswer with the summary as text. Do not call any tools."
)

TOOL_RESULT_REMOVED = (
    "[This tool result was removed to fit the model's context window. "
    "Run the tool again if you need it.]"
)


def cache_read_rate(model: Optional[str]) -> float:
    """What a cached input token costs relative to an uncached one."""
    # shortcut: Anthropic's prices by model name; add a model here when its
    # cache price differs, or read prices from the provider if they change often.
    name = (model or "").lower().replace(".", "-")
    if "fable" in name or "mythos" in name:
        return 0.025
    if "opus-5-5" in name or "sonnet-5-5" in name:
        return 0.05
    return 0.1


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


def _json_chars(messages: list[dict]) -> int:
    return sum(len(json.dumps(m)) for m in messages if m.get("role") != "system")


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


def compaction_estimate(usage, summary_usage, removed_share=None) -> dict:
    """Context use after compacting, from the reply's usage and the summary call's.

    The summary's tokens replace the removed conversation. A summary call
    sent fresh reads only the conversation and the instructions. One that
    reads the cache also reads the system prompt and tools, so
    ``removed_share`` gives the conversation's share of its prompt.
    """
    usage = usage if isinstance(usage, dict) else {}
    summary_usage = summary_usage if isinstance(summary_usage, dict) else {}
    used = usage.get("context_used")
    window = usage.get("context_window")
    prompt = summary_usage.get("prompt_tokens")
    added = summary_usage.get("completion_tokens")
    if not all(isinstance(v, (int, float)) for v in (used, window, prompt, added)):
        return {}
    if removed_share is None:
        removed = prompt - len(SUMMARY_INSTRUCTIONS) // CHARS_PER_TOKEN
    else:
        removed = prompt * removed_share
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


def _summary_text(response) -> tuple[str, Optional[dict]]:
    if not isinstance(response, dict):
        raise ValueError("The summary call returned no reply")
    choices = response.get("choices") or []
    message = (choices[0] if choices else {}).get("message") or {}
    summary = message.get("content")
    if message.get("tool_calls") or not isinstance(summary, str) or not summary.strip():
        raise ValueError("The summary call returned no text")
    return summary.strip(), response.get("usage")


async def _call_model(request, user, model_id: str, form: dict):
    from open_webui.utils.chat import generate_chat_completion
    from open_webui.utils.models import remember_catalog_model

    # A server that has not served this model since it started has not loaded it.
    await asyncio.to_thread(remember_catalog_model, request, model_id)
    response = await generate_chat_completion(
        request, {"model": model_id, "stream": False, **form}, user
    )
    return _summary_text(response)


def final_reply_text(chain: list[dict]) -> Optional[str]:
    """The text of the reply's last model call, which its cached request lacks."""
    last = chain[-1] if chain else None
    if not last or last.get("role") != "assistant":
        return None
    expanded = expand_ui_tool_history_messages([last])
    final = expanded[-1] if expanded else None
    if not final or final.get("role") != "assistant" or final.get("tool_calls"):
        return None
    return _text(final.get("content")).strip() or None


class CachedPlan(NamedTuple):
    """A summary call that reads the chat's prompt cache."""

    payload: Optional[str]  # the stored request extended, sent as is
    messages: Optional[list]  # the turn's messages, sent as a model call
    removed_share: float  # the conversation's share of the request


class Started(NamedTuple):
    children: list
    usage: Optional[dict]
    running: dict
    prompt: str
    plan: Optional[CachedPlan]


def _cached_plan(chain, message_id, warm, turn_messages, tools, context_tokens, fresh_chars):
    """A CachedPlan when reading the cache costs less than the fresh summary call.

    Reading costs the whole context at the cache price; the fresh call costs
    the conversation at full price.
    """
    if warm is None or not isinstance(context_tokens, (int, float)):
        return None
    call, _ = warm
    body = json.loads(call.payload)
    if cache_read_rate(body.get("model")) * context_tokens >= fresh_chars / CHARS_PER_TOKEN:
        return None
    instructions = {"role": "user", "content": CACHED_INSTRUCTIONS}

    if turn_messages is not None:
        messages = [*turn_messages, instructions]
        total = len(json.dumps(messages)) + len(json.dumps(tools or []))
        return CachedPlan(None, messages, _json_chars(turn_messages) / max(total, 1))

    if (call.reply_usage or {}).get("message_id") != message_id:
        return None
    final = final_reply_text(chain)
    if not final:
        return None
    body["messages"] = [
        *body.get("messages", []),
        {"role": "assistant", "content": final},
        instructions,
    ]
    removed = _json_chars(body["messages"][:-1])
    body.pop("stream_options", None)
    body.pop("max_completion_tokens", None)
    body.update(stream=False, max_tokens=SUMMARY_MAX_TOKENS)
    if isinstance(body.get("trace"), dict):
        body["trace"]["generation_name"] = "chat-compaction"
    payload = json.dumps(body)
    return CachedPlan(payload, None, removed / max(len(payload), 1))


def _start_compaction(
    chat_id: str,
    message_id: str,
    message_map: Optional[dict],
    usage: Optional[dict],
    warm,
    turn_messages: Optional[list],
    tools: Optional[list],
    context_tokens: Optional[int],
) -> Optional[Started]:
    """Read the chat, build the summary request, and save the running state.

    Synchronous: a database read, the transcript build and the cached request
    (both grow with the chat) and a write, so compact_chat runs it in one
    thread. None when the message is gone. Nothing is written when the
    request cannot be built.
    """
    chat = Chats.get_chat_by_id(chat_id)
    document = dict(chat.chat) if chat else {}
    history = document.get("history") or {}
    message = (history.get("messages") or {}).get(message_id)
    if not isinstance(message, dict):
        return None
    if message_map:
        document["history"] = {**history, "messages": message_map}
    chain = messages_for_model(document, message_id)
    prompt = summary_request(chain)
    usage = usage or message.get("usage") or {}
    if context_tokens is None:
        context_tokens = usage.get("context_used")
    plan = _cached_plan(
        chain, message_id, warm, turn_messages, tools, context_tokens, len(prompt)
    )
    running = {"status": "running", "started_at": int(time.time())}
    Chats.set_message_compaction(chat_id, message_id, running, bump_revision=False)
    return Started(
        list(message.get("childrenIds") or []), usage, running, prompt, plan
    )


async def _summarize(request, user, model_id, started: Started, metadata, warm, tools):
    """The summary and its context estimate: from the cache when planned, else fresh."""
    plan = started.plan
    if plan is not None:
        try:
            if plan.payload is not None:
                from open_webui.routers.openai import send_after_call

                response = await send_after_call(warm[0], warm[1], plan.payload, "task")
                summary, summary_usage = _summary_text(response)
            else:
                from open_webui.routers.openai import PREVIOUS_TURN_KEY

                summary, summary_usage = await _call_model(
                    request,
                    user,
                    model_id,
                    {
                        "messages": plan.messages,
                        **({"tools": tools} if tools else {}),
                        # The turn's calls keep the conversation before it cached here.
                        "metadata": {**metadata, PREVIOUS_TURN_KEY: 2},
                    },
                )
            return summary, compaction_estimate(
                started.usage, summary_usage, plan.removed_share
            )
        except Exception:
            log.info("Cached summary call failed; sending it fresh", exc_info=True)
    summary, summary_usage = await _call_model(
        request,
        user,
        model_id,
        {"messages": [{"role": "user", "content": started.prompt}], "metadata": metadata},
    )
    return summary, compaction_estimate(started.usage, summary_usage)


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
    turn_messages: Optional[list] = None,
    tools: Optional[list] = None,
    context_tokens: Optional[int] = None,
) -> dict:
    """Summarize the chat up to and including message_id and save it there.

    Returns the saved compaction, or ``{"status": "failed"}`` or
    ``{"status": "cancelled"}`` when a new turn was added to that message
    meanwhile. At the end of a turn the reply's final text and usage may not
    be saved yet, so the caller passes them as message_map and usage. During
    a reply, turn_messages and tools are the turn's request up to that
    message and context_tokens the turn's last prompt size.
    """
    from open_webui.utils import cache_keepalive

    warm = cache_keepalive.warm_call(chat_id)
    if warm is not None and getattr(warm[1], "id", None) != user.id:
        warm = None  # its usage and model access belong to another user
    try:
        started = await asyncio.to_thread(
            _start_compaction,
            chat_id,
            message_id,
            message_map,
            usage,
            warm,
            turn_messages,
            tools,
            context_tokens,
        )
    except Exception:
        log.warning("Chat compaction failed chat_id=%s", chat_id, exc_info=True)
        started = None
    if started is None:
        await _emit(emitter_meta, chat_id, message_id, {"status": "failed"})
        return {"status": "failed"}
    await _emit(emitter_meta, chat_id, message_id, started.running)

    compaction = None
    outcome = "failed"
    try:
        summary, estimate = await asyncio.wait_for(
            _summarize(
                request,
                user,
                model_id,
                started,
                {
                    "task": "chat_compaction",
                    "chat_id": chat_id,
                    "user_id": user.id,
                    "organization_id": organization_id,
                },
                warm,
                tools,
            ),
            COMPACTION_TIMEOUT_S,
        )
        done = {
            "status": "done",
            "summary": summary,
            "model": model_id,
            "created_at": int(time.time()),
            **estimate,
        }
        if await asyncio.to_thread(
            Chats.set_message_compaction,
            chat_id,
            message_id,
            done,
            children=started.children,
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


def _last_user_index(messages: list[dict]) -> Optional[int]:
    return max(
        (i for i, m in enumerate(messages) if m.get("role") == "user"), default=None
    )


def previous_turn_marker(base: list[dict], call: list[dict]) -> dict:
    """Metadata telling the model call where the turns before this one end.

    base is the turn's messages up to its user message; call is what is sent.
    """
    from open_webui.routers.openai import PREVIOUS_TURN_KEY

    last_user = _last_user_index(base)
    if not last_user:
        return {}
    return {PREVIOUS_TURN_KEY: len(call) - (last_user - 1)}


def compacted_messages(messages: list[dict], summary: str, notes: str) -> list[dict]:
    """The call's messages after compacting everything before this turn.

    Keeps the leading system messages and the turn from its user message on;
    the summary and the chat's notes move onto that user message.
    """
    last_user = _last_user_index(messages)
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
    tools: Optional[list] = None,
) -> tuple[list[dict], list[dict]]:
    """Before a model call, make it fit the model's context window.

    base is the turn's messages before this turn's tool calls; call is what
    the model gets, and tools the turn's tools. used_before is the prompt
    tokens of the turn's previous call (or the context the previous reply
    ended at) and chars_before the characters it was counted for; None
    estimates the whole call from its characters. Over the window, the chat
    is compacted up to the reply this turn follows, once per turn; then the
    oldest tool results are dropped from the call. Returns the new base and
    call.
    """
    try:
        return await _fit_model_call(
            request, user, model, metadata, base, call, used_before, chars_before, tools
        )
    except Exception:
        # Sending the call as it was is no worse than before this check.
        log.warning("Fitting a model call failed", exc_info=True)
        return base, call


async def _fit_model_call(
    request, user, model, metadata, base, call, used_before, chars_before, tools
):
    from open_webui.routers.openai import context_window_for

    if not (model or {}).get("id"):
        return base, call
    window = await context_window_for(request, user, model["id"])
    if not window or _estimate(call, used_before, chars_before) <= window:
        return base, call

    state = metadata.get("compaction")
    parent = (state or {}).get("parent") or {}
    last_user = _last_user_index(base)
    if (
        state
        and not state.get("done")
        and parent.get("id")
        and last_user
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
            turn_messages=base[:last_user],
            tools=tools,
            context_tokens=used_before,
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
    request, user, model: dict, metadata: dict, messages: list[dict], tools=None
) -> list[dict]:
    """fit_model_call for a turn's first call, estimated from the previous reply.

    That reply's context use covers everything but the new user message.
    """
    parent = ((metadata.get("compaction") or {}).get("parent")) or {}
    used = (parent.get("usage") or {}).get("context_used")
    last_user = next((m for m in reversed(messages) if m.get("role") == "user"), None)
    chars_before = message_chars(messages) - message_chars([last_user] if last_user else [])
    _, call = await fit_model_call(
        request, user, model, metadata, messages, messages, used, chars_before, tools
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
