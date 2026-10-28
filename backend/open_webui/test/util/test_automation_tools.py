"""Built-in tools to create, list, edit, and delete scheduled tasks."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.models.automations import AutomationForm, AutomationRuns, Automations
from open_webui.utils import builtin_tools
from open_webui.utils.builtin_tools import (
    delete_scheduled_task,
    get_builtin_tools,
    list_scheduled_tasks,
    update_scheduled_task,
)

TASK_TOOLS = {
    "create_scheduled_task",
    "list_scheduled_tasks",
    "update_scheduled_task",
    "delete_scheduled_task",
}


class AutomationToolsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4()}"
        self.other = f"other-{uuid.uuid4()}"
        self.org = f"org-{uuid.uuid4()}"
        self.admins: set[str] = set()
        self.personal_orgs: set[str] = set()
        users = {
            uid: SimpleNamespace(id=uid, name=uid, role="user")
            for uid in (self.owner, self.other)
        }
        patches = [
            patch.object(builtin_tools.Users, "get_user_by_id", side_effect=users.get),
            patch.object(builtin_tools, "sync_automation_job"),
            patch.object(builtin_tools, "remove_automation_job"),
            patch.object(builtin_tools, "is_member", return_value=True),
            patch("open_webui.utils.organizations.is_member", return_value=True),
            patch(
                "open_webui.utils.organizations.is_org_admin",
                side_effect=lambda org_id, user_id: user_id in self.admins,
            ),
            patch(
                "open_webui.utils.organizations.is_personal_org",
                side_effect=lambda org_id: org_id in self.personal_orgs,
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _automation(self, name="Daily map", visibility="private", user_id=None, **kw):
        automation = Automations.insert_new_automation(
            user_id or self.owner,
            AutomationForm(
                name=name,
                prompt=kw.pop("prompt", "Make the SMAP map for Kenya."),
                cron=kw.pop("cron", "0 7 * * *"),
                organization_id=self.org,
                visibility=visibility,
                **kw,
            ),
        )
        self.addCleanup(Automations.delete_automation, automation.id)
        return automation

    def _as(self, user_id):
        return {"__user__": {"id": user_id}}

    def _in_chat(self, user_id):
        return {
            **self._as(user_id),
            "__metadata__": {"chat_id": "chat-1", "organization_id": self.org},
        }

    async def test_list_shows_own_and_shared_automations_with_last_run(self):
        mine = self._automation("Daily map")
        shared = self._automation("Team chart", visibility="organization", user_id=self.other)
        hidden = self._automation("Other private", user_id=self.other)
        AutomationRuns.insert_run(
            mine.id, status="error", triggered_by="schedule", error="403: Model not found"
        )

        result = await list_scheduled_tasks(**self._in_chat(self.owner))

        self.assertIn(mine.id, result)
        self.assertIn("Daily map", result)
        self.assertIn("0 7 * * *", result)
        self.assertIn("403: Model not found", result)
        self.assertIn(shared.id, result)
        self.assertNotIn(hidden.id, result)

    async def test_list_one_automation_shows_its_whole_prompt(self):
        long_prompt = "Step one. " * 100 + "THE END"
        automation = self._automation(prompt=long_prompt)
        summary = await list_scheduled_tasks(**self._in_chat(self.owner))
        self.assertNotIn("THE END", summary)
        detail = await list_scheduled_tasks(task_id=automation.id, **self._in_chat(self.owner))
        self.assertIn("THE END", detail)

    async def test_update_changes_the_given_fields_and_reschedules(self):
        automation = self._automation()
        result = await update_scheduled_task(
            task_id=automation.id,
            name="Weekly map",
            schedule="daily at 6:30pm",
            **self._as(self.owner),
        )
        updated = Automations.get_automation_by_id(automation.id)
        self.assertEqual(updated.name, "Weekly map")
        self.assertEqual(updated.cron, "30 18 * * *")
        self.assertEqual(updated.prompt, automation.prompt)
        self.assertIn("Weekly map", result)
        builtin_tools.sync_automation_job.assert_called_once()

    async def test_update_refuses_a_bad_schedule(self):
        automation = self._automation()
        result = await update_scheduled_task(
            task_id=automation.id, schedule="whenever", **self._as(self.owner)
        )
        self.assertIn("could not understand that schedule", result)
        self.assertEqual(Automations.get_automation_by_id(automation.id).cron, "0 7 * * *")

    async def test_moving_to_a_personal_org_makes_it_private(self):
        automation = self._automation(visibility="organization")
        personal = f"personal-{uuid.uuid4()}"
        self.personal_orgs.add(personal)
        await update_scheduled_task(
            task_id=automation.id, organization_id=personal, **self._as(self.owner)
        )
        updated = Automations.get_automation_by_id(automation.id)
        self.assertEqual(updated.organization_id, personal)
        self.assertEqual(updated.visibility, "private")

    async def test_only_managers_can_update_or_delete(self):
        automation = self._automation(visibility="organization")
        result = await update_scheduled_task(
            task_id=automation.id, name="Hijacked", **self._as(self.other)
        )
        self.assertIn("cannot change", result)
        result = await delete_scheduled_task(task_id=automation.id, **self._as(self.other))
        self.assertIn("cannot change", result)
        self.assertIsNotNone(Automations.get_automation_by_id(automation.id))

        self.admins.add(self.other)
        await update_scheduled_task(
            task_id=automation.id, name="Renamed by admin", **self._as(self.other)
        )
        self.assertEqual(
            Automations.get_automation_by_id(automation.id).name, "Renamed by admin"
        )

    async def test_delete_removes_the_automation_and_its_schedule(self):
        automation = self._automation()
        result = await delete_scheduled_task(task_id=automation.id, **self._as(self.owner))
        self.assertIn("Deleted", result)
        self.assertIsNone(Automations.get_automation_by_id(automation.id))
        builtin_tools.remove_automation_job.assert_called_once_with(automation.id)

    async def test_unknown_automation(self):
        result = await delete_scheduled_task(task_id="nope", **self._as(self.owner))
        self.assertIn("not found", result)


class AutomationToolsOfferedTest(unittest.TestCase):
    def _names(self, metadata):
        return set(get_builtin_tools({"__metadata__": metadata}))

    def test_offered_in_a_chat(self):
        self.assertTrue(TASK_TOOLS <= self._names({"chat_id": "c"}))

    def test_not_offered_in_an_automation_run(self):
        self.assertFalse(TASK_TOOLS & self._names({"chat_id": "c", "headless": True}))


if __name__ == "__main__":
    unittest.main()
