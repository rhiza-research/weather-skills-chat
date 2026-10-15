from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from open_webui.utils.builtin_tools import _rag_from_artifact_file, read_artifact
from open_webui.utils.middleware import files_ready_for_model
from open_webui.utils.model_messages import (
    attach_read_artifact_images,
    read_artifact_image_urls,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class ReadArtifactImageUrlsTest(unittest.TestCase):
    def test_collects_only_read_artifact_data_urls(self):
        blocks = [
            {
                "type": "tool_calls",
                "content": [
                    {"id": "c1", "function": {"name": "display_image"}},
                    {"id": "c2", "function": {"name": "read_artifact"}},
                ],
                "results": [
                    {
                        "tool_call_id": "c1",
                        "files": ["data:image/png;base64,display"],
                    },
                    {
                        "tool_call_id": "c2",
                        "files": ["data:image/png;base64,read"],
                    },
                ],
            }
        ]
        self.assertEqual(
            read_artifact_image_urls(blocks), ["data:image/png;base64,read"]
        )

    def test_appends_image_after_tool_results(self):
        messages = [
            {"role": "user", "content": "Look at photo.png"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c2",
                        "type": "function",
                        "function": {"name": "read_artifact", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c2", "content": "approved"},
        ]
        blocks = [
            {
                "type": "tool_calls",
                "content": [{"id": "c2", "function": {"name": "read_artifact"}}],
                "results": [
                    {
                        "tool_call_id": "c2",
                        "files": ["data:image/png;base64,abc"],
                    }
                ],
            }
        ]
        out = attach_read_artifact_images(messages, blocks)
        self.assertEqual(out[0]["content"], "Look at photo.png")
        self.assertEqual(out[-1]["role"], "user")
        content = out[-1]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertIn("read_artifact", content[0]["text"])
        self.assertEqual(
            content[1],
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        )

    def test_does_not_replay_image_after_later_tool_wave(self):
        messages = [
            {"role": "user", "content": "fix the plot"},
            {"role": "assistant", "content": None, "tool_calls": []},
            {"role": "tool", "tool_call_id": "c2", "content": "approved"},
            {"role": "assistant", "content": None, "tool_calls": []},
            {"role": "tool", "tool_call_id": "p1", "content": "plotted"},
        ]
        blocks = [
            {
                "type": "tool_calls",
                "content": [{"id": "c2", "function": {"name": "read_artifact"}}],
                "results": [
                    {
                        "tool_call_id": "c2",
                        "files": ["data:image/png;base64,stale"],
                    }
                ],
            },
            {"type": "text", "content": ""},
            {
                "type": "tool_calls",
                "content": [{"id": "p1", "function": {"name": "plot"}}],
                "results": [{"tool_call_id": "p1", "content": "plotted"}],
            },
        ]
        out = attach_read_artifact_images(messages, blocks)
        self.assertEqual(out, messages)
        self.assertFalse(
            any(
                isinstance(m.get("content"), list)
                and any(part.get("type") == "image_url" for part in m["content"])
                for m in out
            )
        )


class FilesReadyForModelTest(unittest.TestCase):
    def test_skips_images_and_awaiting_approval(self):
        files = [
            {"type": "collection", "id": "kb"},
            {"type": "file", "name": "notes.csv", "awaitingApproval": True},
            {"type": "file", "name": "ready.csv"},
            {"type": "image", "url": "data:image/png;base64,abc"},
        ]
        ready = files_ready_for_model(files)
        self.assertEqual(
            [(item.get("type"), item.get("name") or item.get("id")) for item in ready],
            [("collection", "kb"), ("file", "ready.csv")],
        )


class ReadArtifactBuiltinTest(unittest.TestCase):
    def test_read_artifact_is_always_available(self):
        from open_webui.utils.builtin_tools import get_builtin_tools

        tools = get_builtin_tools({"__metadata__": {"features": {}}})
        self.assertIn("read_artifact", tools)
        self.assertEqual(tools["read_artifact"]["spec"]["name"], "read_artifact")


class ReadArtifactToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_temporary_chat(self):
        out = await read_artifact(
            path="a.csv", __user__={"id": "u1"}, __metadata__={"chat_id": "local"}
        )
        self.assertIn("temporary chat", out)

    async def test_decline_does_not_send_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-read"
            root = artifacts / chat_id
            root.mkdir(parents=True)
            (root / "notes.csv").write_text("a,b\n1,2\n", encoding="utf-8")

            event_call = AsyncMock(return_value=False)
            user = MagicMock(id="u1")
            chat = MagicMock()
            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.utils.builtin_tools.Users") as users,
                patch("open_webui.utils.builtin_tools.Chats") as chats,
                patch("open_webui.utils.builtin_tools.can_read_chat", return_value=True),
            ):
                users.get_user_by_id.return_value = user
                chats.get_chat_by_id.return_value = chat
                out = await read_artifact(
                    path="notes.csv",
                    __user__={"id": "u1"},
                    __metadata__={"chat_id": chat_id},
                    __event_call__=event_call,
                )

            self.assertIn("declined", out)
            event_call.assert_awaited_once()
            payload = event_call.await_args.args[0]
            self.assertEqual(payload["type"], "confirmation")
            self.assertIn("notes.csv", payload["data"]["message"])

    async def test_approved_image_reads_from_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-img"
            root = artifacts / chat_id
            root.mkdir(parents=True)
            (root / "photo.png").write_bytes(PNG)

            event_call = AsyncMock(return_value=True)
            user = MagicMock(id="u1")
            chat = MagicMock()
            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.utils.builtin_tools.Users") as users,
                patch("open_webui.utils.builtin_tools.Chats") as chats,
                patch("open_webui.utils.builtin_tools.can_read_chat", return_value=True),
                patch(
                    "open_webui.utils.builtin_tools.display_image",
                    new_callable=AsyncMock,
                    return_value=["Showing `photo.png`.", "data:image/png;base64,fromdisk"],
                ) as display,
            ):
                users.get_user_by_id.return_value = user
                chats.get_chat_by_id.return_value = chat
                out = await read_artifact(
                    path="photo.png",
                    __user__={"id": "u1"},
                    __metadata__={"chat_id": chat_id},
                    __event_call__=event_call,
                )

            self.assertEqual(
                out,
                [
                    (
                        "The user approved reading `photo.png`. "
                        "The image is attached as a vision input after this tool result."
                    ),
                    "data:image/png;base64,fromdisk",
                ],
            )
            display.assert_awaited_once()
            self.assertEqual(display.await_args.kwargs["path"], "photo.png")

    async def test_approved_csv_indexes_from_sandbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-csv"
            root = artifacts / chat_id
            root.mkdir(parents=True)
            (root / "notes.csv").write_text("a,b\n1,2\n", encoding="utf-8")

            event_call = AsyncMock(return_value=True)
            user = MagicMock(id="u1")
            chat = MagicMock()
            request = MagicMock()
            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.utils.builtin_tools.Users") as users,
                patch("open_webui.utils.builtin_tools.Chats") as chats,
                patch("open_webui.utils.builtin_tools.can_read_chat", return_value=True),
                patch(
                    "open_webui.utils.builtin_tools._rag_from_artifact_file",
                    new_callable=AsyncMock,
                    return_value="<source id=\"1\">a,b</source>",
                ) as rag,
            ):
                users.get_user_by_id.return_value = user
                chats.get_chat_by_id.return_value = chat
                out = await read_artifact(
                    path="notes.csv",
                    __user__={"id": "u1"},
                    __metadata__={"chat_id": chat_id},
                    __event_call__=event_call,
                    __request__=request,
                    __messages__=[{"role": "user", "content": "summarize this"}],
                    __model__={"id": "demo"},
                )

            self.assertIn("notes.csv", out)
            rag.assert_awaited_once()
            self.assertEqual(rag.await_args.args[2], "notes.csv")
            self.assertEqual(rag.await_args.args[3].name, "notes.csv")
            self.assertTrue(rag.await_args.args[3].is_file())

    async def test_refuses_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-dir"
            root = artifacts / chat_id
            (root / "plots").mkdir(parents=True)

            event_call = AsyncMock(return_value=True)
            user = MagicMock(id="u1")
            chat = MagicMock()
            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.utils.builtin_tools.Users") as users,
                patch("open_webui.utils.builtin_tools.Chats") as chats,
                patch("open_webui.utils.builtin_tools.can_read_chat", return_value=True),
            ):
                users.get_user_by_id.return_value = user
                chats.get_chat_by_id.return_value = chat
                out = await read_artifact(
                    path="plots",
                    __user__={"id": "u1"},
                    __metadata__={"chat_id": chat_id},
                    __event_call__=event_call,
                )

            self.assertIn("folder", out)
            event_call.assert_not_awaited()

    async def test_headless_session_does_not_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-headless"
            root = artifacts / chat_id
            root.mkdir(parents=True)
            (root / "notes.csv").write_text("a,b\n", encoding="utf-8")

            event_call = AsyncMock(
                return_value={"error": "Client-side execution is unavailable"}
            )
            user = MagicMock(id="u1")
            chat = MagicMock()
            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.utils.builtin_tools.Users") as users,
                patch("open_webui.utils.builtin_tools.Chats") as chats,
                patch("open_webui.utils.builtin_tools.can_read_chat", return_value=True),
            ):
                users.get_user_by_id.return_value = user
                chats.get_chat_by_id.return_value = chat
                out = await read_artifact(
                    path="notes.csv",
                    __user__={"id": "u1"},
                    __metadata__={"chat_id": chat_id},
                    __event_call__=event_call,
                )

            self.assertIn("declined", out)

    async def test_rag_from_artifact_indexes_then_uses_files_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "notes.csv"
            path.write_text("a,b\n1,2\n", encoding="utf-8")
            request = MagicMock()
            request.app.state.config.BYPASS_EMBEDDING_AND_RETRIEVAL = False
            request.app.state.config.RAG_FULL_CONTEXT = False
            user = MagicMock()
            doc = MagicMock(page_content="a,b 1,2", metadata={})
            loader = MagicMock()
            loader.load.return_value = [doc]
            with (
                patch(
                    "open_webui.utils.builtin_tools._content_loader",
                    return_value=loader,
                ),
                patch(
                    "open_webui.routers.retrieval.save_docs_to_vector_db"
                ) as save_docs,
                patch(
                    "open_webui.utils.builtin_tools._insert_rag_for_file",
                    new_callable=AsyncMock,
                    return_value="indexed",
                ) as insert,
            ):
                out = await _rag_from_artifact_file(
                    request,
                    user,
                    "notes.csv",
                    path,
                    [{"role": "user", "content": "q"}],
                    "demo",
                )

            self.assertEqual(out, "indexed")
            loader.load.assert_called_once()
            self.assertEqual(loader.load.call_args.args[2], str(path))
            save_docs.assert_called_once()
            file_item = insert.await_args.args[2]
            self.assertEqual(file_item["name"], "notes.csv")
            self.assertIn("collection_name", file_item)
            self.assertNotEqual(file_item.get("context"), "full")
