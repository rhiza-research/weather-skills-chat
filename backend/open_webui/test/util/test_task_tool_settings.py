"""The model's scheduled task tools set everything the task page can."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.models.automations import AutomationForm, Automations
from open_webui.utils import builtin_tools
from open_webui.utils.builtin_tools import (
    create_scheduled_task,
    list_scheduled_tasks,
    update_scheduled_task,
)


def _request(enabled=("web_search", "code_interpreter", "image_generation")):
    config = SimpleNamespace(
        ENABLE_WEB_SEARCH="web_search" in enabled,
        ENABLE_CODE_INTERPRETER="code_interpreter" in enabled,
        ENABLE_IMAGE_GENERATION="image_generation" in enabled,
        USER_PERMISSIONS={},
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=config)))


class TaskToolSettingsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4()}"
        self.org = f"org-{uuid.uuid4()}"
        self.personal_orgs = {self.owner}
        self.user = SimpleNamespace(id=self.owner, name="Owner", role="admin")
        chat = SimpleNamespace(
            id="chat-1",
            chat={"models": ["chat-model"]},
            organization_id=self.org,
            visibility="private",
        )
        skills = [
            {"id": "skill_plot", "skill_name": "plot", "version": "1.0.0"},
            {"id": "skill_smap", "skill_name": "smap-fetch", "version": "1.0.0"},
        ]
        models = {"chat-model", "other-model"}

        def remember(request, model_id):
            return {"id": model_id} if model_id in models else None

        patches = [
            patch.object(builtin_tools.Users, "get_user_by_id", return_value=self.user),
            patch.object(builtin_tools.Chats, "get_chat_by_id", return_value=chat),
            patch.object(builtin_tools, "can_read_chat", return_value=True),
            patch.object(builtin_tools, "is_member", return_value=True),
            patch.object(builtin_tools, "sync_automation_job"),
            patch("open_webui.utils.organizations.is_member", return_value=True),
            patch(
                "open_webui.utils.organizations.is_personal_org",
                side_effect=lambda org_id: org_id in self.personal_orgs,
            ),
            patch("open_webui.utils.models.remember_catalog_model", side_effect=remember),
            patch("open_webui.utils.models.check_model_access"),
            patch("open_webui.utils.tools.accessible_skill_records", return_value=skills),
            patch(
                "open_webui.utils.automation_runner._accessible_tool_ids",
                return_value=["skill_plot", "skill_smap", "my_tool"],
            ),
            patch(
                "open_webui.models.automations.Tools.get_tool_catalog", return_value=[]
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _ctx(self, request=None):
        return {
            "__user__": {"id": self.owner},
            "__metadata__": {
                "chat_id": "chat-1",
                "organization_id": self.org,
                "tool_ids": ["skill_plot"],
                "features": {"web_search": True},
            },
            "__request__": request or _request(),
        }

    def _only_task(self):
        tasks = Automations.get_automations_for_user(self.owner, self.org)
        self.assertEqual(len(tasks), 1)
        self.addCleanup(Automations.delete_automation, tasks[0].id)
        return tasks[0]

    async def _create(self, **kw):
        return await create_scheduled_task(
            name="Daily map", schedule="daily at 6am", prompt="Make the map.", **kw, **self._ctx()
        )

    async def test_create_copies_the_chat_unless_told_otherwise(self):
        await self._create()
        task = self._only_task()
        self.assertEqual(task.model, "chat-model")
        self.assertEqual(task.tool_ids, ["skill_plot"])
        self.assertEqual(task.features, {"web_search": True})
        self.assertEqual(task.visibility, "private")

    async def test_create_sets_every_setting(self):
        result = await self._create(
            model="other-model",
            skills=["smap-fetch", "my_tool"],
            web_search=False,
            code_interpreter=True,
            image_generation=True,
            read_files=True,
            email=False,
            preferences=False,
            shared=True,
        )
        task = self._only_task()
        self.assertEqual(task.model, "other-model")
        self.assertEqual(task.tool_ids, ["smap-fetch", "my_tool"])
        self.assertEqual(
            task.features,
            {
                "web_search": False,
                "code_interpreter": True,
                "image_generation": True,
                "read_artifacts": True,
                "email": False,
                "preferences": False,
            },
        )
        self.assertEqual(task.visibility, "organization")
        self.assertIn("Daily map", result)

    async def test_update_changes_only_what_is_passed(self):
        await self._create()
        task = self._only_task()
        await update_scheduled_task(
            task_id=task.id,
            model="other-model",
            skills=[],
            read_files=True,
            shared=True,
            enabled=False,
            **{k: v for k, v in self._ctx().items() if k != "__metadata__"},
        )
        updated = Automations.get_automation_by_id(task.id)
        self.assertEqual(updated.model, "other-model")
        self.assertEqual(updated.tool_ids, [])
        self.assertEqual(updated.features, {"web_search": True, "read_artifacts": True})
        self.assertEqual(updated.visibility, "organization")
        self.assertFalse(updated.enabled)
        self.assertEqual(updated.name, "Daily map")
        builtin_tools.sync_automation_job.assert_called()

    async def test_update_can_remove_the_picture(self):
        await self._create()
        task = self._only_task()
        Automations.set_image(task.id, b"webp")
        await update_scheduled_task(
            task_id=task.id,
            remove_picture=True,
            **{k: v for k, v in self._ctx().items() if k != "__metadata__"},
        )
        self.assertIsNone(Automations.get_automation_by_id(task.id).image_updated_at)

    async def test_unknown_model_and_skills_are_refused(self):
        result = await self._create(model="nope")
        self.assertIn("model", result.lower())
        result = await self._create(skills=["plot", "made-up"])
        self.assertIn("made-up", result)
        self.assertEqual(Automations.get_automations_for_user(self.owner, self.org), [])

    async def test_features_the_admin_turned_off_cannot_be_turned_on(self):
        result = await create_scheduled_task(
            name="Daily map",
            schedule="daily at 6am",
            prompt="Make the map.",
            code_interpreter=True,
            **{**self._ctx(), "__request__": _request(enabled=("web_search",))},
        )
        self.assertIn("code", result.lower())
        self.assertEqual(Automations.get_automations_for_user(self.owner, self.org), [])

    async def test_a_personal_task_cannot_be_shared(self):
        self.personal_orgs.add(self.org)
        result = await self._create(shared=True)
        self.assertIn("personal", result)

    async def test_the_list_shows_the_settings(self):
        await self._create(skills=["smap-fetch"], read_files=True, email=False)
        self._only_task()
        ctx = self._ctx()
        result = await list_scheduled_tasks(
            __user__=ctx["__user__"], __metadata__=ctx["__metadata__"]
        )
        self.assertIn("skills and tools: smap-fetch", result)
        self.assertIn("web search", result)
        self.assertIn("read files", result)
        self.assertIn("email off", result)


if __name__ == "__main__":
    unittest.main()
