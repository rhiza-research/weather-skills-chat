"""Compact a chat: a model summary replaces its earlier messages for the model.

The summary is saved on the reply where the chat was compacted, as
``compaction``; ``chat_turns.messages_for_model`` leaves out everything up to
it. The person still sees every message.

``compact`` runs one compaction, for Compact now or the app. ``ContextBudget``
follows one turn's context use and calls it: during the reply when the next
model call would not fit, and after the reply when the context is over 90%.
"""

import asyncio
import json
import logging
import time
from typing import NamedTuple, Optional

from fastapi import HTTPException, status

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

Many parts of the chat can likely be made concise by describing the final result of a set of analysis and/or tool calls. Please be as concise as reasonably possible without preventing continued analysis.

Answer with the summary as text. Do not call any tools."""

TOOL_RESULT_REMOVED = (
    "[This tool result was removed to fit the model's context window. "
    "Run the tool again if you need it.]"
)


# ---------------------------------------------------------------- transcript


def _text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for part in content if isinstance(content, list) else []:
        if isinstance(part, dict) and part.get("type") == "text":
            parts.append(part.get("text") or "")
        elif isinstance(part, dict) and part.get("type") == "image_url":
            parts.append("[image]")
    return "\n".join(parts)


def _chars(messages: list[dict]) -> int:
    """Characters of the text a model call sends, for estimating its tokens."""
    total = 0
    for message in messages:
        total += len(_text(message.get("content")))
        if message.get("tool_calls"):
            total += len(json.dumps(message["tool_calls"]))
    return total


def transcript_text(messages: list[dict]) -> str:
    """The conversation as one text, so the fresh summary call sends no tool turns."""
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


def final_reply_text(chain: list[dict]) -> Optional[str]:
    """The text of the reply's last model call, which that call's request lacks."""
    if not chain or chain[-1].get("role") != "assistant":
        return None
    final = expand_ui_tool_history_messages([chain[-1]])[-1:]
    if not final or final[0].get("role") != "assistant" or final[0].get("tool_calls"):
        return None
    return _text(final[0].get("content")).strip() or None


# ------------------------------------------------------------ one compaction


def compaction_running(compaction, now: Optional[float] = None) -> bool:
    """A compaction still running; one older than the timeout died with its server."""
    if not isinstance(compaction, dict) or compaction.get("status") != "running":
        return False
    started = compaction.get("started_at")
    if not isinstance(started, (int, float)):
        return False
    return (now if now is not None else time.time()) - started < COMPACTION_TIMEOUT_S


class _Job(NamedTuple):
    children: list  # the reply's replies when it started; a new one cancels it
    usage: dict  # the reply's context use
    model_id: Optional[str]
    transcript: str
    final: Optional[str]  # the reply's last text, to re-send its cached call
    running: dict


def _check_reply(message) -> None:
    """Refuse compacting at a message a person picked that cannot be compacted."""
    if not isinstance(message, dict) or message.get("role") != "assistant":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Only a reply can be compacted.")
    if message.get("done") is False:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Wait for the reply to finish.")
    compaction = message.get("compaction") or {}
    if compaction.get("status") == "done":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="The chat is already compacted here.")
    if compaction_running(compaction):
        raise HTTPException(status.HTTP_409_CONFLICT, detail="The chat is already being compacted.")
    if not message.get("model"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="This reply has no model to compact with."
        )


def _begin(chat_id, reply_id, reply_map, usage, check_reply) -> Optional[_Job]:
    """Read the chat, build the transcript, and save the running state.

    Synchronous: a database read, the transcript (which grows with the chat)
    and a write, so compact runs it in one thread. None when the reply is
    gone; nothing is saved when the transcript cannot be built.
    """
    chat = Chats.get_chat_by_id(chat_id)
    document = dict(chat.chat) if chat else {}
    history = document.get("history") or {}
    message = (history.get("messages") or {}).get(reply_id)
    if check_reply:
        _check_reply(message)
    if not isinstance(message, dict):
        return None
    if reply_map:
        document["history"] = {**history, "messages": reply_map}
    chain = messages_for_model(document, reply_id)
    running = {"status": "running", "started_at": int(time.time())}
    job = _Job(
        list(message.get("childrenIds") or []),
        usage or message.get("usage") or {},
        message.get("model"),
        transcript_text(chain),
        final_reply_text(chain),
        running,
    )
    Chats.set_message_compaction(chat_id, reply_id, running, bump_revision=False)
    return job


def _summary_text(response) -> tuple[str, dict]:
    choices = response.get("choices") if isinstance(response, dict) else None
    message = (choices[0] if choices else {}).get("message") or {}
    summary = message.get("content")
    if message.get("tool_calls") or not isinstance(summary, str) or not summary.strip():
        raise ValueError("The summary call returned no summary")
    return summary.strip(), response.get("usage") or {}


async def _resend(user, chat_id, reply_id, job) -> Optional[tuple[str, dict, int]]:
    """The summary from the reply's own last call, re-sent while it is cached."""
    from open_webui.routers.openai import resend_last_call

    if not job.final:
        return None
    try:
        sent = await resend_last_call(
            chat_id,
            user,
            reply_id,
            [
                {"role": "assistant", "content": job.final},
                {"role": "user", "content": SUMMARY_INSTRUCTIONS},
            ],
            SUMMARY_MAX_TOKENS,
        )
        if sent is None:
            return None
        return (*_summary_text(sent[0]), sent[1])
    except Exception:
        log.info("Summary from the cached call failed; sending it fresh", exc_info=True)
        return None


async def _summarize(request, user, chat_id, reply_id, job, metadata):
    """The summary, its call's usage, and the characters that call was sent."""
    from open_webui.utils.chat import generate_chat_completion
    from open_webui.utils.models import remember_catalog_model

    resent = await _resend(user, chat_id, reply_id, job)
    if resent is not None:
        return resent
    prompt = f"{SUMMARY_INSTRUCTIONS}\n\n<conversation>\n{job.transcript}\n</conversation>"
    # A server that has not served this model since it started has not loaded it.
    await asyncio.to_thread(remember_catalog_model, request, job.model_id)
    response = await generate_chat_completion(
        request,
        {
            "model": job.model_id,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "metadata": metadata,
        },
        user,
    )
    return (*_summary_text(response), len(prompt))


def context_after(job_usage, summary_usage, transcript_chars, sent_chars) -> dict:
    """Context use after compacting: the reply's, less the conversation, plus the summary.

    The conversation's tokens use the tokens per character the summary call
    reported for what it was sent.
    """
    used = job_usage.get("context_used")
    window = job_usage.get("context_window")
    prompt = summary_usage.get("prompt_tokens")
    added = summary_usage.get("completion_tokens")
    if not all(isinstance(v, (int, float)) for v in (used, window, prompt, added)):
        return {}
    removed = prompt * transcript_chars / max(sent_chars, 1)
    return {
        "context_estimate": max(int(used - removed + added), int(added)),
        "context_window": window,
    }


async def _notify(notify: dict, chat_id: str, reply_id: str, data: dict) -> None:
    from open_webui.socket.main import get_event_emitter

    emitter = get_event_emitter(
        {**notify, "chat_id": chat_id, "message_id": reply_id}, update_db=False
    )
    try:
        await emitter({"type": "chat:compaction", "data": data})
    except Exception:
        log.debug("compaction event failed chat_id=%s", chat_id, exc_info=True)


async def compact(
    request,
    user,
    chat_id: str,
    reply_id: str,
    *,
    notify: dict,
    organization_id: Optional[str] = None,
    usage: Optional[dict] = None,
    reply_map: Optional[dict] = None,
    check_reply: bool = False,
) -> dict:
    """Summarize the chat up to and including reply_id and save it there.

    The reply's own model writes the summary. Returns the saved compaction,
    or {"status": "failed"}, or {"status": "cancelled"} when a message was
    added after the reply meanwhile. At the end of a turn the reply's final
    text and usage may not be saved yet, so the caller passes reply_map and
    usage. check_reply refuses a reply a person picked that cannot be
    compacted, with HTTPException; notify addresses the page's events.
    """
    try:
        job = await asyncio.to_thread(
            _begin, chat_id, reply_id, reply_map, usage, check_reply
        )
    except HTTPException:
        raise
    except Exception:
        log.warning("Chat compaction failed chat_id=%s", chat_id, exc_info=True)
        job = None
    if job is None:
        await _notify(notify, chat_id, reply_id, {"status": "failed"})
        return {"status": "failed"}
    await _notify(notify, chat_id, reply_id, job.running)

    result = {"status": "failed"}
    try:
        summary, summary_usage, sent_chars = await asyncio.wait_for(
            _summarize(
                request,
                user,
                chat_id,
                reply_id,
                job,
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
            "model": job.model_id,
            "created_at": int(time.time()),
            **context_after(job.usage, summary_usage, len(job.transcript), sent_chars),
        }
        saved = await asyncio.to_thread(
            Chats.set_message_compaction, chat_id, reply_id, done, children=job.children
        )
        result = done if saved else {"status": "cancelled"}
    except Exception:
        log.warning("Chat compaction failed chat_id=%s", chat_id, exc_info=True)

    if result["status"] != "done":
        try:
            await asyncio.to_thread(Chats.set_message_compaction, chat_id, reply_id, None)
        except Exception:
            log.warning("Could not clear compaction chat_id=%s", chat_id, exc_info=True)
    await _notify(notify, chat_id, reply_id, result)
    return result


# ------------------------------------------------------------------ one turn


def _last_user_index(messages: list[dict]) -> Optional[int]:
    return max((i for i, m in enumerate(messages) if m.get("role") == "user"), default=None)


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


def drop_old_tool_results(messages: list[dict], excess_chars: int) -> list[dict]:
    """Replace the oldest tool results with a note until excess_chars are gone."""
    out = list(messages)
    for index, message in enumerate(out):
        if excess_chars <= 0:
            break
        if message.get("role") == "tool" and message.get("content") != TOOL_RESULT_REMOVED:
            excess_chars -= len(_text(message.get("content"))) - len(TOOL_RESULT_REMOVED)
            out[index] = {**message, "content": TOOL_RESULT_REMOVED}
    return out


class ContextBudget:
    """One turn's context use, kept within the model's context window.

    fit() runs before each model call of the turn and record() after it;
    finish() runs once the reply is done. The chat is compacted at most once
    per turn. Without chat_id (no saved turn) it only drops old tool results.
    """

    def __init__(
        self,
        chat_id: Optional[str] = None,
        reply_id: Optional[str] = None,
        parent: Optional[dict] = None,
    ):
        self.chat_id = chat_id
        self.reply_id = reply_id
        self.parent = parent or {}  # the saved reply this turn follows
        self.compacted = False
        self.usage: dict = {}  # the last call's usage, with its context use
        self.sent_chars: Optional[int] = None  # characters that call was sent

    def record(self, usage: Optional[dict]) -> None:
        if isinstance(usage, dict):
            self.usage = usage

    def _first_call(self, call: list[dict]) -> None:
        """Before the turn's first call: the reply before it ended at this size."""
        last_user = _last_user_index(call)
        new = call[last_user : last_user + 1] if last_user is not None else []
        self.usage = {"prompt_tokens": (self.parent.get("usage") or {}).get("context_used")}
        self.sent_chars = _chars(call) - _chars(new)

    def _estimate(self, call: list[dict]) -> int:
        """The call's prompt tokens: the last call's, plus what was added since."""
        known = self.usage.get("prompt_tokens")
        if not isinstance(known, (int, float)):
            return _chars(call) // CHARS_PER_TOKEN
        return int(known + (_chars(call) - self.sent_chars) // CHARS_PER_TOKEN)

    async def fit(self, request, user, model, metadata, base, call):
        """Make the next call fit the window. base is the turn's messages up to its
        tool calls; call is what the model gets. Returns the new base and call."""
        if self.sent_chars is None:
            self._first_call(call)
        try:
            base, call = await self._fit(request, user, model or {}, metadata, base, call)
        except Exception:
            log.warning("Fitting a model call failed", exc_info=True)
        self.sent_chars = _chars(call)
        return base, call

    async def _fit(self, request, user, model, metadata, base, call):
        from open_webui.routers.openai import context_window_for

        window = await context_window_for(request, user, model["id"]) if model.get("id") else None
        if not window or self._estimate(call) <= window:
            return base, call
        parent_compaction = self.parent.get("compaction") or {}
        if (
            self.chat_id
            and self.parent.get("id")
            and not self.compacted
            and parent_compaction.get("status") != "done"
            and not compaction_running(parent_compaction)
        ):
            self.compacted = True
            result = await compact(
                request,
                user,
                self.chat_id,
                self.parent["id"],
                notify=metadata,
                organization_id=metadata.get("organization_id"),
            )
            if result["status"] == "done":
                chat = await asyncio.to_thread(Chats.get_chat_by_id, self.chat_id)
                notes = "\n\n".join(n for n in (chat.chat if chat else {}).get("chatNotes") or [] if n)
                new_base = compacted_messages(base, result["summary"], notes)
                call, base = [*new_base, *call[len(base) :]], new_base
        excess = (self._estimate(call) - window) * CHARS_PER_TOKEN
        return base, drop_old_tool_results(call, excess)

    async def finish(self, request, user, metadata, reply_map) -> None:
        """After the reply: compact at it when the context is over 90% full."""
        used = self.usage.get("context_used")
        window = self.usage.get("context_window")
        if self.compacted or not self.chat_id or not used or not window:
            return
        if used <= END_OF_TURN_RATIO * window:
            return
        self.compacted = True
        await compact(
            request,
            user,
            self.chat_id,
            self.reply_id,
            notify=metadata,
            organization_id=metadata.get("organization_id"),
            usage=self.usage,
            reply_map=reply_map,
        )
