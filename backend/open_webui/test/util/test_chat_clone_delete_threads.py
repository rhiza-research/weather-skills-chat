"""Cloning a chat copies its files in the background; deleting removes them off the event loop."""

import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI

from open_webui.routers import chats as chats_router
from open_webui.utils.auth import get_verified_user

USER = SimpleNamespace(id="u1", role="user")
CHAT = SimpleNamespace(
    id="chat-1",
    title="Weekly rainfall",
    organization_id="u1",
    meta={"tags": []},
    chat={"history": {"currentId": "m1", "messages": {}}},
)


class CloneDeleteThreadsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop_thread = threading.current_thread()
        self.ran_on = {}
        app = FastAPI()
        app.include_router(chats_router.router, prefix="/api/v1/chats")
        app.dependency_overrides[get_verified_user] = lambda: USER
        app.state.config = SimpleNamespace(USER_PERMISSIONS={})
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    def record(self, name, result=None):
        def call(*args, **kwargs):
            self.ran_on[name] = threading.current_thread()
            return result

        return call

    async def test_clone_returns_at_once_and_copies_its_files_in_the_background(self):
        clone = MagicMock(model_dump=lambda: {"id": "chat-2", "user_id": "u1", "title": "Copy", "chat": {}, "created_at": 1, "updated_at": 1, "archived": False, "pinned": False, "meta": {}, "folder_id": None, "share_id": None})
        clone.id = "chat-2"
        order = []
        copy_may_finish = threading.Event()

        def copy(src, dest):
            self.ran_on["copy"] = threading.current_thread()
            copy_may_finish.wait(5)
            order.append(("copy", src, dest))

        with patch.object(chats_router, "_require_readable_chat", self.record("read", CHAT)), patch.object(
            chats_router.Chats, "insert_new_chat", return_value=clone
        ) as insert, patch(
            "open_webui.utils.artifacts.mark_copy_started", lambda chat_id: order.append(("marked", chat_id))
        ), patch("open_webui.utils.artifacts.copy_sandbox", copy):
            response = await self.client.post("/api/v1/chats/chat-1/clone", json={"title": "Copy"})
            # The clone comes back while its files are still being copied.
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(order, [("marked", "chat-2")])
            copy_may_finish.set()
            await asyncio.gather(*chats_router._artifact_copies)

        self.assertEqual(order, [("marked", "chat-2"), ("copy", "chat-1", "chat-2")])
        # The clone keeps the conversation.
        self.assertEqual(insert.call_args.args[1].chat["history"], CHAT.chat["history"])
        for name in ("read", "copy"):
            self.assertIsNot(self.ran_on[name], self.loop_thread, name)
        self.assertEqual(chats_router._artifact_copies, set())

    async def test_clone_from_share_link_lands_in_the_active_organization(self):
        snapshot = SimpleNamespace(
            id="share-1", user_id="shared-chat-1", title="Weekly rainfall", chat=CHAT.chat
        )
        clone = MagicMock(model_dump=lambda: {"id": "chat-2", "user_id": "u1", "title": "Copy", "chat": {}, "created_at": 1, "updated_at": 1, "archived": False, "pinned": False, "meta": {}, "folder_id": None, "share_id": None})
        clone.id = "chat-2"
        self.client._transport.app.dependency_overrides[
            chats_router.get_active_organization_id
        ] = lambda: "org-team"
        with patch.object(chats_router.Chats, "get_chat_by_share_id", return_value=snapshot), patch.object(
            chats_router.Chats, "insert_new_chat", return_value=clone
        ) as insert, patch("open_webui.utils.artifacts.mark_copy_started") as marked, patch(
            "open_webui.utils.artifacts.copy_sandbox"
        ) as copy:
            response = await self.client.post("/api/v1/chats/share-1/clone/shared")
            await asyncio.gather(*chats_router._artifact_copies)

        self.assertEqual(response.status_code, 200, response.text)
        marked.assert_called_once_with("chat-2")
        copy.assert_called_once_with("share-1", "chat-2")
        form = insert.call_args.args[1]
        self.assertEqual((form.organization_id, form.visibility), ("org-team", "private"))

    async def test_new_chat_with_artifacts_returns_at_once_and_copies_in_the_background(self):
        clone = MagicMock(model_dump=lambda: {"id": "chat-2", "user_id": "u1", "title": "New Chat", "chat": {}, "created_at": 1, "updated_at": 1, "archived": False, "pinned": False, "meta": {}, "folder_id": None, "share_id": None})
        clone.id = "chat-2"
        order = []
        copy_may_finish = threading.Event()

        def copy(src, dest):
            self.ran_on["copy"] = threading.current_thread()
            copy_may_finish.wait(5)
            order.append(("copy", src, dest))

        with patch.object(chats_router, "_require_readable_chat", self.record("read", CHAT)), patch.object(
            chats_router.Chats, "insert_new_chat", return_value=clone
        ) as insert, patch(
            "open_webui.utils.artifacts.artifact_carryover_note", self.record("note", "the files")
        ), patch(
            "open_webui.utils.artifacts.mark_copy_started", lambda chat_id: order.append(("marked", chat_id))
        ), patch("open_webui.utils.artifacts.copy_sandbox", copy):
            response = await self.client.post("/api/v1/chats/chat-1/new-with-artifacts")
            # The chat comes back while its files are still being copied.
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(order, [("marked", "chat-2")])
            copy_may_finish.set()
            await asyncio.gather(*chats_router._artifact_copies)

        self.assertEqual(order, [("marked", "chat-2"), ("copy", "chat-1", "chat-2")])
        form = insert.call_args.args[1]
        self.assertEqual(form.chat["history"], {"messages": {}, "currentId": None})
        self.assertEqual(form.chat["chatNotes"], ["the files"])
        self.assertEqual(form.visibility, "private")
        for name in ("read", "note", "copy"):
            self.assertIsNot(self.ran_on[name], self.loop_thread, name)
        self.assertEqual(chats_router._artifact_copies, set())

    async def test_delete_checks_access_and_removes_files_on_a_worker_thread(self):
        with patch.object(chats_router, "has_permission", return_value=True), patch.object(
            chats_router, "_require_writable_chat", self.record("check", CHAT)
        ), patch("open_webui.utils.artifacts.delete_sandbox", self.record("files")), patch.object(
            chats_router.Chats, "delete_chat_by_id_and_user_id", return_value=True
        ), patch(
            "open_webui.utils.chat_realtime.publish_chat_removed", AsyncMock()
        ) as removed:
            response = await self.client.delete("/api/v1/chats/chat-1")

        self.assertEqual(response.status_code, 200, response.text)
        for name in ("check", "files"):
            self.assertIsNot(self.ran_on[name], self.loop_thread, name)
        self.assertIs(self.ran_on["check"], self.ran_on["files"])
        removed.assert_awaited_once_with(CHAT)

    async def test_delete_without_permission_is_refused(self):
        with patch.object(chats_router, "has_permission", return_value=False), patch(
            "open_webui.utils.artifacts.delete_sandbox", self.record("files")
        ):
            response = await self.client.delete("/api/v1/chats/chat-1")

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("files", self.ran_on)
