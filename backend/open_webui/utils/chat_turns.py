"""Append one client-minted turn and rebuild the model transcript from storage."""

import logging
import re
from typing import Optional

from fastapi import HTTPException, status

from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.chats import Chats
from open_webui.utils.misc import get_message_list
from open_webui.utils.organizations import can_write_chat

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

_HIDDEN_DETAILS = re.compile(
    r'<details\s+type="(?:reasoning|code_interpreter)"[^>]*>.*?</details>',
    re.IGNORECASE | re.DOTALL,
)


class ChatRevisionConflict(Exception):
    def __init__(self, revision: int):
        super().__init__("Chat was updated")
        self.revision = revision


def messages_for_model(history: dict, message_id: str) -> list[dict]:
    """Linearize a stored history the way the client used to, minus hidden details."""
    bag = (history or {}).get("messages") or {}
    chain = get_message_list(bag, message_id) or []
    prepared = []
    for message in chain:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        merged = message.get("merged") if isinstance(message.get("merged"), dict) else {}
        content = merged.get("content")
        if content is None:
            content = message.get("content")
        if isinstance(content, str):
            content = _HIDDEN_DETAILS.sub("", content)
        item = {"role": role, "content": content}
        if message.get("tool_calls"):
            item["tool_calls"] = message["tool_calls"]
        if message.get("tool_call_id"):
            item["tool_call_id"] = message["tool_call_id"]
        files = message.get("files") or []
        images = [
            file
            for file in files
            if isinstance(file, dict) and file.get("type") == "image" and role == "user"
        ]
        if images and isinstance(content, str):
            item["content"] = [
                {"type": "text", "text": content},
                *[
                    {"type": "image_url", "image_url": {"url": file.get("url")}}
                    for file in images
                    if file.get("url")
                ],
            ]
        if role in ("user", "system", "tool"):
            prepared.append(item)
            continue
        if item.get("tool_calls"):
            prepared.append(item)
            continue
        body = item.get("content")
        if isinstance(body, str) and body.strip():
            prepared.append(item)
        elif isinstance(body, list) and body:
            prepared.append(item)
    return prepared


def prepare_completion_messages(chat_id: str, turn: dict, user) -> list[dict]:
    """Store the new user and assistant messages, then build the model transcript.

    A mismatched ``expected_revision`` does not write. The caller turns that
    into a conflict the client refetches.
    """
    if not isinstance(turn, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid turn")
    user_message = turn.get("user_message")
    assistant_message = turn.get("assistant_message")
    if not isinstance(user_message, dict) or not user_message.get("id"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Missing user message")
    if not isinstance(assistant_message, dict) or not assistant_message.get("id"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="Missing assistant message"
        )

    chat = Chats.get_chat_by_id(chat_id)
    if chat is None or not can_write_chat(user, chat):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Access prohibited")

    expected: Optional[int]
    if "expected_revision" in turn and turn.get("expected_revision") is not None:
        try:
            expected = int(turn["expected_revision"])
        except (TypeError, ValueError):
            expected = None
    else:
        expected = None

    try:
        stored, state = Chats.append_turn(
            chat_id,
            user_message,
            assistant_message,
            expected,
        )
    except Exception as exc:
        from open_webui.models.chats import ChatWriteError

        if isinstance(exc, ChatWriteError):
            raise HTTPException(
                status.HTTP_409_CONFLICT if exc.busy else status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
        raise
    if state == "conflict":
        from open_webui.utils.chat_realtime import chat_revision, schedule_chat_committed

        schedule_chat_committed(chat_id)
        raise ChatRevisionConflict(chat_revision(stored) if stored else 0)
    if state == "invalid":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="The parent message for this turn is missing.",
        )
    if state == "error" or stored is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="The chat could not be saved. Please try again.",
        )

    history = (stored.chat or {}).get("history") or {}
    return messages_for_model(history, assistant_message["id"])
