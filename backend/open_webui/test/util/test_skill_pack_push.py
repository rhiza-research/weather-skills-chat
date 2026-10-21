"""Pushing skill packs to a runner keeps JuiceFS, DB and compression work off the event loop."""

import base64
import io
import json
import os
import tarfile
import tempfile
import threading
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from open_webui.utils import skill_k8s_sandbox as sandbox

INFO = {"pod_ip": "10.0.0.1", "pod_name": "runner-1"}


class UnpackRequestTest(TestCase):
    def test_body_holds_the_pack_archive_without_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Path(tmp) / "weather-skills"
            (pack / "skills" / "plot").mkdir(parents=True)
            (pack / "skills" / "plot" / "SKILL.md").write_text("# plot\n")
            (pack / "__pycache__").mkdir()
            (pack / "__pycache__" / "x.pyc").write_bytes(b"\0")
            with patch.dict(os.environ, {"SKILLS_DIR": tmp}):
                dest, body = sandbox._unpack_request(pack / "skills" / "plot")

        self.assertEqual(dest, f"{sandbox._runner_packs_root()}/weather-skills")
        payload = json.loads(body)
        self.assertEqual(payload["dest"], dest)
        archive = base64.b64decode(payload["archive"])
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
            names = tar.getnames()
        self.assertIn("weather-skills/skills/plot/SKILL.md", names)
        self.assertFalse(any("__pycache__" in name for name in names))


class PackPushOffLoopTest(IsolatedAsyncioTestCase):
    async def test_pack_is_built_on_a_worker_thread_and_sent_as_bytes(self):
        loop_thread = threading.current_thread()
        seen = {}

        def build(skill_dir):
            seen["thread"] = threading.current_thread()
            return "/packs/weather-skills", b'{"dest": "/packs/weather-skills", "archive": ""}'

        http = AsyncMock(return_value={"ok": True})
        with patch.object(sandbox, "_runner_base", AsyncMock(return_value="http://r")), patch.object(
            sandbox, "_unpack_request", build
        ), patch.object(sandbox, "_http_json", http):
            dest = await sandbox._ensure_pack_on_runner(INFO, Path("/skills/weather-skills"))

        self.assertEqual(dest, "/packs/weather-skills")
        self.assertIsNot(seen["thread"], loop_thread)
        self.assertEqual(http.call_args.args, ("POST", "http://r/unpack"))
        self.assertEqual(
            http.call_args.kwargs["json_bytes"],
            b'{"dest": "/packs/weather-skills", "archive": ""}',
        )
        self.assertNotIn("json_body", http.call_args.kwargs)

    async def test_chat_packs_are_looked_up_on_a_worker_thread(self):
        loop_thread = threading.current_thread()
        threads = []

        def packs_for_chat(chat_id):
            threads.append(threading.current_thread())
            return [Path("/skills/weather-skills")]

        with patch.object(sandbox, "_packs_for_chat", packs_for_chat), patch.object(
            sandbox, "_listed_packs", AsyncMock(return_value={"weather-skills"})
        ):
            await sandbox._ensure_packs_on_runner(INFO, "chat-1")
            ready = await sandbox._packs_ready_on_runner(
                {"metadata": {"annotations": {}}, "status": {"podIP": "10.0.0.1"}},
                "chat-1",
                INFO,
            )

        self.assertTrue(ready)
        self.assertEqual(len(threads), 2)
        self.assertTrue(all(thread is not loop_thread for thread in threads))


class HttpJsonBytesTest(IsolatedAsyncioTestCase):
    async def test_pre_encoded_body_is_sent_as_json(self):
        sent = {}

        class Response:
            status = 200

            async def read(self):
                return b'{"ok": true}'

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

        class Session:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            def request(self, method, url, **kwargs):
                sent.update(kwargs)
                return Response()

        with patch.object(sandbox.aiohttp, "ClientSession", Session):
            result = await sandbox._http_json("POST", "http://r/unpack", json_bytes=b'{"a": 1}')

        self.assertEqual(result, {"ok": True})
        self.assertEqual(sent["data"], b'{"a": 1}')
        self.assertIsNone(sent["json"])
        self.assertEqual(sent["headers"]["Content-Type"], "application/json")


class PacksForChatTest(TestCase):
    def test_reads_only_the_chat_owner_and_organization(self):
        from unittest.mock import MagicMock

        from open_webui.models.chats import ChatAccessRow

        row = ChatAccessRow(id="chat-1", user_id="u1", organization_id="org-1", visibility="private")
        user = MagicMock(id="u1")
        with patch("open_webui.models.chats.Chats") as chats, patch(
            "open_webui.models.users.Users"
        ) as users, patch("open_webui.models.tools.Tools") as tools, patch(
            "open_webui.utils.tools.accessible_skill_records", return_value=[]
        ) as records:
            chats.get_chat_access_row.return_value = row
            users.get_user_by_id.return_value = user
            tools.get_tool_catalog.return_value = []
            self.assertEqual(sandbox._packs_for_chat("chat-1"), [])

        chats.get_chat_access_row.assert_called_once_with("chat-1")
        chats.get_chat_by_id.assert_not_called()
        users.get_user_by_id.assert_called_once_with("u1")
        self.assertEqual(records.call_args.kwargs["organization_id"], "org-1")

    def test_missing_chat_lists_no_packs(self):
        with patch("open_webui.models.chats.Chats") as chats:
            chats.get_chat_access_row.return_value = None
            self.assertEqual(sandbox._packs_for_chat("gone"), [])
