"""Callers that only check access read the chat's access row, not the whole chat."""

from __future__ import annotations

import ast
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from open_webui.models.chats import ChatAccessRow

ROOT = Path(__file__).resolve().parents[2]

# Functions whose only use of the stored chat is the access check (or its
# owner, organization or visibility). They must not load the whole chat.
ACCESS_ONLY = {
    "routers/chats.py": [
        "e2e_age_chat",
        "update_chat_by_id",
        "patch_chat_history",
        "update_chat_message_by_id",
        "send_chat_message_event_by_id",
        "pin_chat_by_id",
        "archive_chat_by_id",
        "update_chat_visibility_by_id",
        "update_chat_folder_id_by_id",
    ],
    "routers/users.py": ["get_user_by_id"],
    "main.py": ["list_tasks_by_chat_id_endpoint", "require_owned_chat"],
    "utils/chat_turns.py": ["prepare_completion_messages"],
    "utils/builtin_tools.py": [
        "copy_intermediate_result",
        "create_folder",
        "list_artifacts",
        "display_image",
        "read_artifact",
        "list_email_recipients",
        "send_email",
        "execute_code",
    ],
}

FULL_CHAT_CALLS = {"get_chat_by_id", "_require_writable_chat", "_require_readable_chat"}


def _row(user_id="u1", visibility="private") -> ChatAccessRow:
    return ChatAccessRow(id="chat-1", user_id=user_id, organization_id=user_id, visibility=visibility)


class AccessOnlyCallersTest(unittest.TestCase):
    def test_access_only_functions_do_not_load_the_whole_chat(self):
        for rel, names in ACCESS_ONLY.items():
            tree = ast.parse((ROOT / rel).read_text())
            functions = {
                node.name: node
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            for name in names:
                self.assertIn(name, functions, f"{rel}:{name} not found")
                called = {
                    node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                    for node in ast.walk(functions[name])
                    if isinstance(node, ast.Call)
                }
                self.assertFalse(called & FULL_CHAT_CALLS, f"{rel}:{name} loads the whole chat")


# Access checks are DB reads (the access row, and organization membership for a
# user who is not the owner). Async code must run them on a worker thread.
ACCESS_CALLS = {
    "get_chat_access_row",
    "require_chat_read",
    "require_chat_write",
    "require_owned_chat",
    "can_read_chat",
    "can_write_chat",
}
ACCESS_FILES = [
    "routers/chats.py",
    "routers/artifacts.py",
    "routers/tool_runner.py",
    "routers/users.py",
    "main.py",
    "utils/chat_turns.py",
    "utils/builtin_tools.py",
    "utils/chat_realtime.py",
]


class AccessChecksOffTheLoopTest(unittest.TestCase):
    def test_no_access_check_runs_directly_in_async_code(self):
        offenders = []
        for rel in ACCESS_FILES:
            tree = ast.parse((ROOT / rel).read_text())
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                if name not in ACCESS_CALLS:
                    continue
                scope = parents.get(node)
                while scope is not None and not isinstance(
                    scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
                ):
                    scope = parents.get(scope)
                if isinstance(scope, ast.AsyncFunctionDef):
                    offenders.append(f"{rel}:{node.lineno} {name} in async {scope.name}")
        self.assertEqual(offenders, [])


class RequireChatAccessTest(unittest.TestCase):
    """The shared route checks read the access row, never the whole chat."""

    def setUp(self):
        from open_webui.utils import organizations

        self.organizations = organizations
        self.chats = MagicMock()
        self.chats.get_chat_by_id.side_effect = AssertionError("loaded the whole chat")
        self.patch = patch.object(organizations, "Chats", self.chats)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_owner_gets_the_access_row(self):
        self.chats.get_chat_access_row.return_value = _row()
        for require in (self.organizations.require_chat_read, self.organizations.require_chat_write):
            row = require("chat-1", MagicMock(id="u1"))
            self.assertEqual(row.user_id, "u1")
        self.chats.get_chat_access_row.assert_called_with("chat-1")

    def test_org_member_can_read_a_shared_chat_but_not_change_it(self):
        self.chats.get_chat_access_row.return_value = _row(user_id="u2", visibility="organization")
        with patch.object(self.organizations, "is_member", return_value=True):
            self.organizations.require_chat_read("chat-1", MagicMock(id="u1"))
            with self.assertRaises(HTTPException) as ctx:
                self.organizations.require_chat_write("chat-1", MagicMock(id="u1"))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_missing_chat_is_refused(self):
        self.chats.get_chat_access_row.return_value = None
        for require in (self.organizations.require_chat_read, self.organizations.require_chat_write):
            with self.assertRaises(HTTPException) as ctx:
                require("chat-1", MagicMock(id="u1"))
            self.assertEqual(ctx.exception.status_code, 401)

    def test_routers_use_the_shared_checks(self):
        for rel in ("routers/artifacts.py", "routers/tool_runner.py", "routers/chats.py"):
            source = (ROOT / rel).read_text()
            for gone in ("def _readable(", "def _writable(", "def _require_writable_access("):
                self.assertNotIn(gone, source, f"{rel} defines its own {gone}")


class BuiltinToolAccessTest(unittest.TestCase):
    def test_create_folder_checks_access_with_the_row(self):
        from open_webui.utils import builtin_tools

        with tempfile.TemporaryDirectory() as tmp, patch(
            "open_webui.utils.artifacts.ARTIFACTS_DIR", Path(tmp)
        ), patch.object(builtin_tools, "Users") as users, patch.object(
            builtin_tools, "Chats"
        ) as chats:
            users.get_user_by_id.return_value = MagicMock(id="u1")
            chats.get_chat_access_row.return_value = _row()
            chats.get_chat_by_id.side_effect = AssertionError("loaded the whole chat")
            out = asyncio.run(
                builtin_tools.create_folder(
                    path="plots", __user__={"id": "u1"}, __metadata__={"chat_id": "chat-1"}
                )
            )
            self.assertTrue((Path(tmp) / "chat-1" / "plots").is_dir(), out)

    def test_another_users_chat_is_refused(self):
        from open_webui.utils import builtin_tools

        with patch.object(builtin_tools, "Users") as users, patch.object(
            builtin_tools, "Chats"
        ) as chats, patch("open_webui.utils.organizations.is_member", return_value=False):
            users.get_user_by_id.return_value = MagicMock(id="u1", role="user")
            chats.get_chat_access_row.return_value = _row(user_id="u2")
            out = asyncio.run(
                builtin_tools.read_artifact(
                    path="notes.csv", __user__={"id": "u1"}, __metadata__={"chat_id": "chat-1"}
                )
            )
        self.assertIn("do not have access", out)


if __name__ == "__main__":
    unittest.main()
