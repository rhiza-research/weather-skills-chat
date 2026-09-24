"""Writes endpoint tool calls into the session's chat row so the interface displays them.

Each call is one assistant message containing only the tool call. No user or model messages are
written. Messages are linked by parentId and childrenIds, which the frontend follows to render.
"""

import logging
import time
import uuid

from open_webui.models.chats import Chats
from open_webui.utils.tool_call_details import completed_tool_call_details

log = logging.getLogger(__name__)

ASSISTANT_ROLE = "assistant"


def _history(session) -> dict:
    return (session.chat or {}).get("history") or {}


def _current_id(session_id: str, fallback) -> str | None:
    """The session's current message id, read from the database now.

    The session object was read before the tool ran. Re-reading it keeps two concurrent calls from
    linking to the same parent.
    """
    current = Chats.get_chat_by_id(session_id)
    if current is None:
        return fallback
    return ((current.chat or {}).get("history") or {}).get("currentId") or fallback


def record_tool_call(session, *, name: str, arguments, result) -> None:
    """Append one completed tool call to the session.

    Exceptions are logged and not raised, so a write failure does not change the tool result.
    """
    try:
        previous_id = _current_id(session.id, _history(session).get("currentId"))
        message_id = str(uuid.uuid4())
        Chats.upsert_message_to_chat_by_id_and_message_id(
            session.id,
            message_id,
            {
                "id": message_id,
                "parentId": previous_id,
                "childrenIds": [],
                "role": ASSISTANT_ROLE,
                "content": completed_tool_call_details(
                    call_id=message_id,
                    name=name,
                    arguments=arguments,
                    result=result,
                ),
                "timestamp": int(time.time()),
            },
        )
        if previous_id:
            _link_child(session.id, previous_id, message_id)
    except Exception:
        log.exception("Could not record an endpoint tool call in session %s", session.id)


def _link_child(session_id: str, parent_id: str, child_id: str) -> None:
    """Add child_id to the parent message's childrenIds."""
    current = Chats.get_chat_by_id(session_id)
    if current is None:
        return
    parent = ((current.chat or {}).get("history") or {}).get("messages", {}).get(
        parent_id
    )
    if parent is None:
        return
    children = list(parent.get("childrenIds") or [])
    if child_id in children:
        return
    children.append(child_id)
    Chats.upsert_message_to_chat_by_id_and_message_id(
        session_id, parent_id, {"childrenIds": children}
    )
    # The upsert sets currentId to the message it wrote, so write the child again to make it
    # current.
    Chats.upsert_message_to_chat_by_id_and_message_id(session_id, child_id, {})
