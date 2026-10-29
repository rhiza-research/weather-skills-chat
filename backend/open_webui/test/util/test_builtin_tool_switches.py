"""Email, scheduled task, and preference tools can be turned off per chat or task."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.utils import builtin_tools
from open_webui.utils.builtin_tools import get_builtin_tools, list_available_tools

EMAIL = {"list_email_recipients", "send_email"}
TASKS = {
    "create_scheduled_task",
    "list_scheduled_tasks",
    "update_scheduled_task",
    "delete_scheduled_task",
}
PREFERENCES = {"list_preferences", "create_preference"}


def _offered(**metadata):
    return set(get_builtin_tools({"__metadata__": {"chat_id": "c", **metadata}}))


class BuiltinSwitchTest(unittest.TestCase):
    def test_on_unless_turned_off(self):
        offered = _offered()
        self.assertTrue(EMAIL | TASKS | PREFERENCES <= offered)
        self.assertTrue(EMAIL | TASKS | PREFERENCES <= _offered(features={"email": True}))

    def test_each_group_turns_off(self):
        self.assertFalse(EMAIL & _offered(features={"email": False}))
        self.assertFalse(TASKS & _offered(features={"scheduled_tasks": False}))
        self.assertFalse(PREFERENCES & _offered(features={"preferences": False}))
        # Turning one off leaves the others.
        self.assertTrue(TASKS | PREFERENCES <= _offered(features={"email": False}))

    def test_a_scheduled_run_never_gets_task_tools(self):
        offered = _offered(headless=True, features={"scheduled_tasks": True})
        self.assertFalse(TASKS & offered)
        self.assertTrue(EMAIL <= offered)


class ListAvailableToolsTest(unittest.IsolatedAsyncioTestCase):
    async def test_lists_only_the_built_ins_offered(self):
        user = SimpleNamespace(id="u1", role="user")
        with patch.object(builtin_tools.Users, "get_user_by_id", return_value=user), patch(
            "open_webui.models.tools.Tools.get_tool_catalog", return_value=[]
        ), patch(
            "open_webui.utils.tools.accessible_skill_records", return_value=[]
        ):
            text = await list_available_tools(
                __user__={"id": "u1"},
                __metadata__={"chat_id": "c", "features": {"email": False}},
            )
        self.assertNotIn("send_email", text)
        self.assertIn("create_scheduled_task", text)
        self.assertIn("list_preferences", text)


if __name__ == "__main__":
    unittest.main()
