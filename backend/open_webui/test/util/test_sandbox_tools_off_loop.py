"""Sandbox tools keep JuiceFS work off the event loop, and a prepared sandbox costs one stat."""

import asyncio
import inspect
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui.utils import artifacts, builtin_tools
from open_webui.utils.tools import get_async_tool_function_and_apply_extra_params

# Tools whose whole body is synchronous file and database work.
THREADED_TOOLS = [
    builtin_tools.copy_intermediate_result,
    builtin_tools.create_folder,
    builtin_tools.display_image,
    builtin_tools.list_artifacts,
    builtin_tools.send_email,
]


class ToolDispatchTest(unittest.TestCase):
    def test_a_plain_tool_runs_on_a_worker_thread(self):
        ran_on = {}

        def tool(x, __user__=None):
            ran_on["thread"] = threading.current_thread()
            return x * 2

        async def run():
            ran_on["loop"] = threading.current_thread()
            call = get_async_tool_function_and_apply_extra_params(tool, {"__user__": {"id": "u1"}})
            return await call(x=21)

        self.assertEqual(asyncio.run(run()), 42)
        self.assertIsNot(ran_on["thread"], ran_on["loop"])

    def test_an_async_tool_still_runs_as_a_coroutine(self):
        async def tool(x):
            return x + 1

        call = get_async_tool_function_and_apply_extra_params(tool, {})
        self.assertTrue(inspect.iscoroutinefunction(call))
        self.assertEqual(asyncio.run(call(x=1)), 2)

    def test_sandbox_tools_are_plain_functions(self):
        for tool in THREADED_TOOLS:
            self.assertFalse(inspect.iscoroutinefunction(tool), tool.__name__)


class ChatSandboxPreparedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.artifacts = Path(self.tmp.name) / "artifacts"
        # chown to our own uid works without root, so the owner check can pass.
        for p in (
            patch.object(artifacts, "ARTIFACTS_DIR", self.artifacts),
            patch.object(artifacts, "SANDBOX_OWNER_UID", os.getuid()),
            patch.object(artifacts, "SANDBOX_OWNER_GID", os.getgid()),
        ):
            p.start()
            self.addCleanup(p.stop)

    def test_a_prepared_sandbox_is_one_stat(self):
        root = artifacts.chat_sandbox("chat-1")
        self.assertTrue((root / "intermediate_results").is_dir())
        with patch.object(artifacts, "make_sandbox_dir") as make, patch.object(
            artifacts.os, "chown"
        ) as chown:
            self.assertEqual(artifacts.chat_sandbox("chat-1"), root)
        make.assert_not_called()
        chown.assert_not_called()

    def test_an_old_sandbox_with_the_wrong_mode_is_repaired(self):
        intermediate = self.artifacts / "chat-old" / "intermediate_results"
        intermediate.mkdir(parents=True)
        os.chmod(intermediate, 0o755)
        artifacts.chat_sandbox("chat-old")
        self.assertEqual(stat.S_IMODE(os.stat(intermediate).st_mode), artifacts.SANDBOX_DIR_MODE)

    def test_a_missing_intermediate_folder_is_recreated(self):
        root = artifacts.chat_sandbox("chat-2")
        os.rmdir(root / "intermediate_results")
        artifacts.chat_sandbox("chat-2")
        self.assertTrue((root / "intermediate_results").is_dir())

    def test_chat_ids_that_are_paths_are_refused(self):
        for bad in ("../escape", "a/b", "..", ".", ""):
            with self.assertRaises(ValueError, msg=bad):
                artifacts.chat_sandbox(bad)


class ReadArtifactParsingTest(unittest.TestCase):
    def test_document_parsing_and_embedding_run_on_a_worker_thread(self):
        ran_on = {}

        def item(request, user, rel, target):
            ran_on["parse"] = threading.current_thread()
            return {"type": "file", "name": rel}

        async def run():
            ran_on["loop"] = threading.current_thread()
            with patch.object(builtin_tools, "_artifact_file_item", item), patch.object(
                builtin_tools, "_insert_rag_for_file", AsyncMock(return_value="context")
            ):
                return await builtin_tools._rag_from_artifact_file(
                    SimpleNamespace(), SimpleNamespace(id="u1"), "notes.csv", Path("notes.csv"), [], None
                )

        self.assertEqual(asyncio.run(run()), "context")
        self.assertIsNot(ran_on["parse"], ran_on["loop"])
