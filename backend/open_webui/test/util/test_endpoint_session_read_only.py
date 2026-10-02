"""The interface cannot replace or edit an endpoint session's messages.

Other chat updates, and every update to an ordinary chat, still go through.
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from open_webui.models.chats import ChatForm
from open_webui.routers import chats as chats_router
from open_webui.utils.endpoint_session import SESSION_MARKER_KEY, is_endpoint_session

USER = SimpleNamespace(id="account-1", role="user")

HISTORY = {"messages": {}, "currentId": None}


def stored(blob):
    return SimpleNamespace(
        id="chat-1",
        chat=blob,
        model_dump=lambda: {},
    )


SESSION = stored({SESSION_MARKER_KEY: True, "title": "MCP session", "history": HISTORY})
ORDINARY = stored({"title": "A chat", "history": HISTORY})


def update(existing, form_chat):
    """Call the update route with the stored chat and access check patched."""
    with patch.object(
        chats_router.Chats, "get_chat_by_id", return_value=existing
    ), patch.object(chats_router, "can_write_chat", return_value=True), patch.object(
        chats_router.Chats, "update_chat_by_id", return_value=existing
    ) as write, patch.object(
        chats_router, "ChatResponse", side_effect=lambda **_: "ok"
    ):
        try:
            result = asyncio.run(
                chats_router.update_chat_by_id(
                    "chat-1", ChatForm(chat=form_chat), user=USER
                )
            )
        except HTTPException as refused:
            return refused, write
        return result, write


def edit_message(existing):
    """Call the message-edit route with the stored chat and access check patched."""
    with patch.object(
        chats_router.Chats, "get_chat_by_id", return_value=existing
    ), patch.object(chats_router, "can_write_chat", return_value=True), patch.object(
        chats_router.Chats, "upsert_message_to_chat_by_id_and_message_id"
    ) as write:
        try:
            asyncio.run(
                chats_router.update_chat_message_by_id(
                    "chat-1",
                    "message-1",
                    chats_router.MessageForm(content="edited"),
                    user=USER,
                )
            )
        except HTTPException as refused:
            return refused, write
        return None, write


class MarkerTest(unittest.TestCase):
    def test_a_marked_blob_is_an_endpoint_session(self):
        self.assertTrue(is_endpoint_session(SESSION.chat))

    def test_an_unmarked_blob_is_not(self):
        self.assertFalse(is_endpoint_session(ORDINARY.chat))

    def test_no_blob_is_not(self):
        self.assertFalse(is_endpoint_session(None))


class UpdateRouteTest(unittest.TestCase):
    def test_replacing_a_sessions_history_is_refused(self):
        refused, write = update(SESSION, {"history": HISTORY})
        self.assertIsInstance(refused, HTTPException)
        self.assertEqual(refused.status_code, 403)
        write.assert_not_called()

    def test_replacing_a_sessions_messages_is_refused(self):
        refused, write = update(SESSION, {"messages": []})
        self.assertIsInstance(refused, HTTPException)
        write.assert_not_called()

    def test_renaming_a_session_is_allowed(self):
        result, write = update(SESSION, {"title": "Renamed"})
        self.assertEqual(result, "ok")
        write.assert_called_once()

    def test_an_ordinary_chats_history_can_be_replaced(self):
        result, write = update(ORDINARY, {"history": HISTORY})
        self.assertEqual(result, "ok")
        write.assert_called_once()


class MessageEditRouteTest(unittest.TestCase):
    def test_editing_a_session_message_is_refused(self):
        refused, write = edit_message(SESSION)
        self.assertIsInstance(refused, HTTPException)
        self.assertEqual(refused.status_code, 403)
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
