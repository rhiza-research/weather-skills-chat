"""A scheduled task records who created it and who last changed it."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.models.automations import AutomationForm, Automations, AutomationUpdateForm
from open_webui.routers import automations as router
from open_webui.utils import builtin_tools
from open_webui.utils.builtin_tools import list_scheduled_tasks, update_scheduled_task


class TaskAuthorshipTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4()}"
        self.admin = f"admin-{uuid.uuid4()}"
        self.org = f"org-{uuid.uuid4()}"
        self.users = {
            self.owner: SimpleNamespace(id=self.owner, name="Ada", role="user"),
            self.admin: SimpleNamespace(id=self.admin, name="Grace", role="user"),
        }
        patches = [
            patch.object(router.Users, "get_user_by_id", side_effect=self.users.get),
            patch.object(builtin_tools.Users, "get_user_by_id", side_effect=self.users.get),
            patch.object(router, "sync_automation_job"),
            patch.object(builtin_tools, "sync_automation_job"),
            patch.object(router, "is_member", return_value=True),
            patch("open_webui.utils.organizations.is_member", return_value=True),
            patch(
                "open_webui.utils.organizations.is_org_admin",
                side_effect=lambda org_id, user_id: user_id == self.admin,
            ),
            patch("open_webui.utils.organizations.is_personal_org", return_value=False),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.task = Automations.insert_new_automation(
            self.owner,
            AutomationForm(
                name="Daily map",
                prompt="Make the map.",
                organization_id=self.org,
                visibility="organization",
            ),
        )
        self.addCleanup(Automations.delete_automation, self.task.id)

    async def _get(self, user_id):
        return await router.get_automation(self.task.id, user=self.users[user_id])

    async def test_a_new_task_was_created_and_last_changed_by_its_creator(self):
        task = await self._get(self.owner)
        self.assertEqual(task.created_by_name, "Ada")
        self.assertEqual(task.updated_by, self.owner)
        self.assertEqual(task.updated_by_name, "Ada")

    async def test_an_edit_records_who_made_it(self):
        saved = await router.update_automation(
            self.task.id,
            AutomationUpdateForm(prompt="Make the bigger map."),
            user=self.users[self.admin],
        )
        self.assertEqual(saved.updated_by_name, "Grace")
        task = await self._get(self.owner)
        self.assertEqual((task.created_by_name, task.updated_by_name), ("Ada", "Grace"))

    async def test_the_models_edits_are_recorded_as_the_user(self):
        await update_scheduled_task(
            task_id=self.task.id, name="Weekly map", __user__={"id": self.admin}
        )
        self.assertEqual(Automations.get_automation_by_id(self.task.id).updated_by, self.admin)

    async def test_a_task_from_before_has_no_updater(self):
        from open_webui.internal.db import get_db
        from open_webui.models.automations import Automation

        with get_db() as db:
            db.query(Automation).filter_by(id=self.task.id).update({"updated_by": None})
            db.commit()
        task = await self._get(self.owner)
        self.assertIsNone(task.updated_by_name)

    async def test_the_model_sees_who_last_changed_a_task(self):
        await update_scheduled_task(
            task_id=self.task.id, name="Weekly map", __user__={"id": self.admin}
        )
        result = await list_scheduled_tasks(
            task_id=self.task.id, __user__={"id": self.owner}, __metadata__={}
        )
        self.assertIn("last changed", result)
        self.assertIn("by Grace", result)


if __name__ == "__main__":
    unittest.main()
