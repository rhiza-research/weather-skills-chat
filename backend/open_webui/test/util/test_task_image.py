"""A scheduled task's optional picture, taken from an image a run reports."""

from __future__ import annotations

import io
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

from open_webui.models.automations import AutomationForm, AutomationRuns, Automations
from open_webui.routers import automations as router
from open_webui.utils import automation_runner, builtin_tools
from open_webui.utils.builtin_tools import report_task_result
from open_webui.utils.task_image import TASK_IMAGE_MAX_SIDE


def _png(width: int, height: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), (30, 120, 200)).save(out, format="PNG")
    return out.getvalue()


class TaskImageTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4()}"
        self.other = f"other-{uuid.uuid4()}"
        self.task = Automations.insert_new_automation(
            self.owner, AutomationForm(name="Daily map", prompt="Make the map.")
        )
        self.addCleanup(Automations.delete_automation, self.task.id)
        self.run = AutomationRuns.insert_run(self.task.id, status="running")
        self.addCleanup(automation_runner._reports.pop, self.run.id, None)

        sandbox = Path(tempfile.mkdtemp())
        (sandbox / "map.png").write_bytes(_png(1600, 800))
        (sandbox / "notes.txt").write_text("not an image")
        patches = [
            patch(
                "open_webui.utils.artifacts.resolve_in_sandbox",
                side_effect=lambda chat_id, rel: sandbox / rel,
            ),
            patch.object(
                builtin_tools,
                "_load_chat_access",
                return_value=builtin_tools.ChatAccess(None, None, True, True),
            ),
            patch.object(builtin_tools, "DISPLAY_IMAGE_WAIT_S", 0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _metadata(self):
        return {
            "__user__": {"id": self.owner},
            "__metadata__": {
                "headless": True,
                "automation_run_id": self.run.id,
                "chat_id": "chat-1",
            },
        }

    async def _report(self, **kw):
        return await report_task_result(
            status=kw.pop("status", "success"),
            summary=kw.pop("summary", "Map made."),
            **kw,
            **self._metadata(),
        )

    def _image(self):
        response = router.get_task_image(self.task.id, user=SimpleNamespace(id=self.owner, role="user"))
        return Image.open(io.BytesIO(response.body))

    async def test_a_reported_image_becomes_the_tasks_picture(self):
        result = await self._report(image="map.png")
        self.assertIn("success", result)
        automation_runner.finish_run(self.run.id)

        task = Automations.get_automation_by_id(self.task.id)
        self.assertIsNotNone(task.image_updated_at)
        image = self._image()
        self.assertLessEqual(max(image.size), TASK_IMAGE_MAX_SIDE)

    async def test_a_bad_image_still_records_the_result(self):
        result = await self._report(status="failure", image="notes.txt")
        self.assertIn("image", result)
        run = automation_runner.finish_run(self.run.id)
        self.assertEqual(run.status, "failure")
        self.assertIsNone(Automations.get_automation_by_id(self.task.id).image_updated_at)

    async def test_an_error_run_keeps_the_old_picture(self):
        await self._report(image="map.png")
        automation_runner.finish_run(self.run.id, error="model down")
        self.assertIsNone(Automations.get_automation_by_id(self.task.id).image_updated_at)

    async def test_a_report_without_an_image_keeps_the_old_picture(self):
        await self._report(image="map.png")
        automation_runner.finish_run(self.run.id)
        before = Automations.get_automation_by_id(self.task.id).image_updated_at

        second = AutomationRuns.insert_run(self.task.id, status="running")
        automation_runner.record_report(second.id, "success", "Map made again.")
        automation_runner.finish_run(second.id)
        self.assertEqual(Automations.get_automation_by_id(self.task.id).image_updated_at, before)

    async def test_managers_can_remove_the_picture(self):
        await self._report(image="map.png")
        automation_runner.finish_run(self.run.id)
        with self.assertRaises(HTTPException):
            router.delete_task_image(self.task.id, user=SimpleNamespace(id=self.other, role="user"))
        router.delete_task_image(self.task.id, user=SimpleNamespace(id=self.owner, role="user"))
        self.assertIsNone(Automations.get_automation_by_id(self.task.id).image_updated_at)
        with self.assertRaises(HTTPException):
            self._image()

    async def test_others_cannot_see_a_private_tasks_picture(self):
        await self._report(image="map.png")
        automation_runner.finish_run(self.run.id)
        with self.assertRaises(HTTPException):
            router.get_task_image(self.task.id, user=SimpleNamespace(id=self.other, role="user"))


if __name__ == "__main__":
    unittest.main()
