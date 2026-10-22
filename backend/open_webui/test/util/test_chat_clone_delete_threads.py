"""Cloning and deleting a chat copy or remove its files off the event loop."""

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

    async def test_clone_reads_the_chat_and_copies_its_files_on_worker_threads(self):
        clone = MagicMock(model_dump=lambda: {"id": "chat-2", "user_id": "u1", "title": "Copy", "chat": {}, "created_at": 1, "updated_at": 1, "archived": False, "pinned": False, "meta": {}, "folder_id": None, "share_id": None})
        clone.id = "chat-2"
        with patch.object(chats_router, "_require_readable_chat", self.record("read", CHAT)), patch.object(
            chats_router.Chats, "insert_new_chat", return_value=clone
        ), patch("open_webui.utils.artifacts.copy_sandbox", self.record("copy")):
            response = await self.client.post("/api/v1/chats/chat-1/clone", json={"title": "Copy"})

        self.assertEqual(response.status_code, 200, response.text)
        for name in ("read", "copy"):
            self.assertIsNot(self.ran_on[name], self.loop_thread, name)

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
