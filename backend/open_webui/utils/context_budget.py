"""Keep the conversation sent to a model under a token budget.

Runs on a copy of the messages before every model call; the saved chat is
never changed. When the estimate is over budget, ``compact_messages`` frees
room oldest-first in two passes:

1. ``compress_turn`` shrinks a turn. Today it clears old tool results and
   keeps the calls, so the model still knows what it ran. A model-written
   summary could replace it later (and would then need storing).
2. ``drop_turn`` removes a whole turn when compressing was not enough.

A turn is a user message and everything up to the next user message, so a
tool call and its result always stay or go together.
"""

from __future__ import annotations

import os

# Share of the model's context window the conversation may fill. The rest is
# room for the reply and for the estimate being off.
MODEL_CONTEXT_BUDGET_PERCENT = float(
    os.environ.get("MODEL_CONTEXT_BUDGET_PERCENT", "85")
)

# shortcut: the window assumed when the provider's model list has none for the
# model (the list is not loaded until someone opens the model picker after a
# restart); fetch the list here if that trims 1M-token models too early.
FALLBACK_CONTEXT_WINDOW = 200_000

# Tool rounds at the end of the conversation that are never cleared.
KEEP_RECENT_ROUNDS = 5

# Providers bill an image by its pixels, not by its base64 length.
IMAGE_TOKENS = 1_600

# Deliberately high: about 3 characters per token, where English prose runs
# nearer 4, so the estimate errs toward trimming early.
CHARS_PER_TOKEN = 3

CLEARED_RESULT = (
    "[Output cleared to fit the model's context limit. "
    "Run the tool again if you need it.]"
)


def context_window(model: dict | None) -> int:
    """The model's context window from its provider model-list entry.

    OpenRouter calls it ``context_length``, Requesty ``context_window``.
    """
    for key in ("context_length", "context_window"):
        value = (model or {}).get(key)
        if isinstance(value, int) and value > 0:
            return value
    return FALLBACK_CONTEXT_WINDOW


def token_budget(model: dict | None) -> int:
    """Most tokens to send this model; 0 or less turns trimming off."""
    return int(context_window(model) * MODEL_CONTEXT_BUDGET_PERCENT / 100)


def estimate_tokens(value) -> int:
    """Rough token count for a message, a list of messages, or any JSON value."""
    if isinstance(value, str):
        return len(value) // CHARS_PER_TOKEN
    if isinstance(value, dict):
        if value.get("type") in ("image_url", "image", "input_image"):
            return IMAGE_TOKENS
        return 4 + sum(estimate_tokens(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(estimate_tokens(v) for v in value)
    return 0


def _split_turns(messages: list[dict]) -> tuple[list[dict], list[list[dict]]]:
    """Messages before the first user message, then one list per turn."""
    head: list[dict] = []
    turns: list[list[dict]] = []
    for message in messages:
        if message.get("role") == "user":
            turns.append([message])
        elif turns:
            turns[-1].append(message)
        else:
            head.append(message)
    return head, turns


def _recent_tool_call_ids(messages: list[dict], rounds: int) -> set[str]:
    """Ids of the tool calls in the last ``rounds`` tool rounds."""
    ids: set[str] = set()
    for message in reversed(messages):
        if rounds <= 0:
            break
        if message.get("role") == "assistant" and message.get("tool_calls"):
            ids.update(call.get("id") for call in message["tool_calls"])
            rounds -= 1
    return ids


def compress_turn(turn: list[dict], need: int, keep: set[str]) -> list[dict]:
    """Shrink a turn by about ``need`` tokens, or as much as it can.

    Clears tool results oldest-first and stops once ``need`` is met, so the
    same history always clears the same results. Results whose call id is
    in ``keep`` are left alone.
    """
    out: list[dict] = []
    for message in turn:
        if (
            need > 0
            and message.get("role") == "tool"
            and message.get("tool_call_id") not in keep
        ):
            saved = estimate_tokens(message.get("content")) - estimate_tokens(
                CLEARED_RESULT
            )
            if saved > 0:
                message = {**message, "content": CLEARED_RESULT}
                need -= saved
        out.append(message)
    return out


def drop_turn(turn: list[dict]) -> list[dict]:
    """Remove a whole turn."""
    return []


def compact_messages(messages: list[dict], budget: int) -> tuple[list[dict], bool]:
    """Fit ``messages`` under ``budget`` tokens; returns (messages, changed).

    The amount freed is rounded up to a quarter of the budget, so the trim
    point stays put while the chat grows and the provider's prompt cache
    keeps hitting. Messages before the first user message, the last turn,
    and the last few tool rounds are never removed or cleared.
    """
    total = estimate_tokens(messages)
    if budget <= 0 or total <= budget:
        return messages, False

    step = max(budget // 4, 1)
    to_free = -(-(total - budget) // step) * step
    head, turns = _split_turns(messages)
    keep = _recent_tool_call_ids(messages, KEEP_RECENT_ROUNDS)
    freed = 0

    for i, turn in enumerate(turns):
        if freed >= to_free:
            break
        before = estimate_tokens(turn)
        turns[i] = compress_turn(turn, to_free - freed, keep)
        freed += before - estimate_tokens(turns[i])

    for i, turn in enumerate(turns[:-1]):
        if freed >= to_free:
            break
        if any(m.get("tool_call_id") in keep for m in turn):
            break
        before = estimate_tokens(turn)
        turns[i] = drop_turn(turn)
        freed += before - estimate_tokens(turns[i])

    if freed <= 0:
        return messages, False
    return head + [m for turn in turns for m in turn], True
