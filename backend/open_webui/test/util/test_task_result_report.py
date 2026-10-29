"""A scheduled task's run ends as what the model reported, unknown, or error."""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from open_webui.models.automations import AutomationForm, AutomationRuns, Automations
from open_webui.utils import automation_runner, builtin_tools
from open_webui.utils.builtin_tools import (
    get_builtin_tools,
    list_scheduled_tasks,
    report_task_result,
)
from open_webui.utils.payload import HEADLESS_SYSTEM_CONTEXT


def _run_metadata(run_id: str) -> dict:
    return {"__metadata__": {"headless": True, "automation_run_id": run_id}}


class ReportToolOfferedTest(unittest.TestCase):
    def _names(self, metadata):
        return set(get_builtin_tools({"__metadata__": metadata}))

    def test_offered_only_in_a_scheduled_run(self):
        self.assertIn(
            "report_task_result",
            self._names({"chat_id": "c", "headless": True, "automation_run_id": "r"}),
        )
        self.assertNotIn("report_task_result", self._names({"chat_id": "c"}))

    def test_headless_context_asks_for_a_report(self):
        self.assertIn("scheduled task", HEADLESS_SYSTEM_CONTEXT)
        self.assertIn("report_task_result", HEADLESS_SYSTEM_CONTEXT)


class ReportToolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.run_id = f"run-{uuid.uuid4()}"
        self.addCleanup(automation_runner._reports.pop, self.run_id, None)

    async def test_records_success_and_failure(self):
        result = await report_task_result(
            status="failure", summary="No SMAP data for today.", **_run_metadata(self.run_id)
        )
        self.assertIn("failure", result)
        self.assertEqual(
            automation_runner._reports[self.run_id], ("failure", "No SMAP data for today.")
        )
        # A later report replaces the earlier one.
        await report_task_result(
            status="Success", summary="Map made.", **_run_metadata(self.run_id)
        )
        self.assertEqual(automation_runner._reports[self.run_id], ("success", "Map made."))

    async def test_rejects_other_statuses_and_empty_summaries(self):
        result = await report_task_result(
            status="error", summary="x", **_run_metadata(self.run_id)
        )
        self.assertIn("success", result)
        result = await report_task_result(
            status="success", summary="  ", **_run_metadata(self.run_id)
        )
        self.assertIn("summary", result)
        self.assertNotIn(self.run_id, automation_runner._reports)

    async def test_outside_a_run(self):
        result = await report_task_result(
            status="success", summary="Done.", __metadata__={"chat_id": "c"}
        )
        self.assertIn("no scheduled task run", result)


class FinishRunTest(unittest.TestCase):
    def setUp(self):
        self.automation_id = f"task-{uuid.uuid4()}"
        self.run = AutomationRuns.insert_run(self.automation_id, status="running")

    def _finish(self, **kw):
        return automation_runner.finish_run(self.run.id, **kw)

    def test_reported_success(self):
        automation_runner.record_report(self.run.id, "success", "Map made.")
        run = self._finish()
        self.assertEqual((run.status, run.summary, run.error), ("success", "Map made.", None))
        self.assertIsNotNone(run.finished_at)

    def test_reported_failure_is_not_an_error(self):
        automation_runner.record_report(self.run.id, "failure", "No data today.")
        run = self._finish()
        self.assertEqual((run.status, run.summary, run.error), ("failure", "No data today.", None))

    def test_no_report_is_unknown(self):
        run = self._finish()
        self.assertEqual((run.status, run.summary), ("unknown", None))

    def test_a_broken_run_is_an_error_even_after_a_report(self):
        automation_runner.record_report(self.run.id, "success", "Map made.")
        run = self._finish(error="429: rate limited")
        self.assertEqual((run.status, run.error), ("error", "429: rate limited"))
        self.assertNotIn(self.run.id, automation_runner._reports)


class ExecuteAutomationReportTest(unittest.IsolatedAsyncioTestCase):
    """The run's final status comes from the model's report."""

    def setUp(self):
        self.owner = f"owner-{uuid.uuid4()}"
        self.automation = Automations.insert_new_automation(
            self.owner,
            AutomationForm(name="Daily map", prompt="Make the map.", model="m"),
        )
        self.addCleanup(Automations.delete_automation, self.automation.id)
        user = SimpleNamespace(id=self.owner, name="Owner", role="admin")
        chat = SimpleNamespace(id=f"chat-{uuid.uuid4()}")
        patches = [
            patch.object(automation_runner.Users, "get_user_by_id", return_value=user),
            patch.object(
                automation_runner, "remember_catalog_model", return_value={"id": "m"}
            ),
            patch.object(automation_runner, "check_usage_caps"),
            patch.object(automation_runner.Chats, "insert_new_chat", return_value=chat),
            patch.object(automation_runner, "_notify_chat_created", AsyncMock()),
            patch(
                "open_webui.utils.chat_realtime.save_final_reply", AsyncMock()
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.request = MagicMock()

    async def _execute(self, stream):
        with patch.object(automation_runner, "_stream_automation_chat", stream):
            return await automation_runner.execute_automation(
                self.request, self.automation.id, "schedule"
            )

    async def test_the_model_reports_failure(self):
        async def stream(request, *, run_id, **kw):
            await report_task_result(
                status="failure", summary="No data today.", **_run_metadata(run_id)
            )

        run = await self._execute(stream)
        self.assertEqual((run.status, run.summary, run.error), ("failure", "No data today.", None))

    async def test_the_model_does_not_report(self):
        run = await self._execute(AsyncMock(return_value=False))
        self.assertEqual(run.status, "unknown")

    async def test_the_run_breaks(self):
        with self.assertRaises(RuntimeError):
            await self._execute(AsyncMock(side_effect=RuntimeError("model down")))
        run = AutomationRuns.get_runs(self.automation.id, limit=1)[0]
        self.assertEqual((run.status, run.error), ("error", "model down"))

    async def test_the_run_id_reaches_the_tools(self):
        seen = {}

        async def stream(request, *, run_id, **kw):
            seen["run_id"] = run_id

        run = await self._execute(stream)
        self.assertEqual(seen["run_id"], run.id)


class StreamMetadataTest(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_carries_the_run_id(self):
        captured = {}

        async def payload(request, form_data, user, metadata, model):
            captured.update(metadata)
            raise RuntimeError("stop")

        with patch.object(automation_runner, "process_chat_payload", payload), patch.object(
            automation_runner, "begin_chat_trace"
        ), patch.object(automation_runner, "end_chat_trace"):
            with self.assertRaises(RuntimeError):
                await automation_runner._stream_automation_chat(
                    MagicMock(),
                    run_id="run-1",
                    chat_id="chat-1",
                    assistant_id="a-1",
                    user=SimpleNamespace(id="u"),
                    model={"id": "m"},
                    model_id="m",
                    prompt="p",
                    tool_ids=None,
                    features={},
                )
        self.assertEqual(captured["automation_run_id"], "run-1")
        self.assertTrue(captured["headless"])


class ListShowsSummaryTest(unittest.IsolatedAsyncioTestCase):
    async def test_last_run_shows_status_and_summary(self):
        owner = f"owner-{uuid.uuid4()}"
        automation = Automations.insert_new_automation(
            owner, AutomationForm(name="Daily map", prompt="Make the map.")
        )
        self.addCleanup(Automations.delete_automation, automation.id)
        run = AutomationRuns.insert_run(automation.id, status="running")
        AutomationRuns.update_run(
            run.id, status="failure", summary="No data today.", finished=True
        )
        user = SimpleNamespace(id=owner, name="Owner", role="user")
        with patch.object(builtin_tools.Users, "get_user_by_id", return_value=user):
            result = await list_scheduled_tasks(
                task_id=automation.id, __user__={"id": owner}, __metadata__={}
            )
        self.assertIn("failure", result)
        self.assertIn("No data today.", result)


if __name__ == "__main__":
    unittest.main()
