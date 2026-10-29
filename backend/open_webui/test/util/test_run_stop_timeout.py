"""A scheduled task's run that a user stops ends as stopped, and one that runs
past its task's time limit ends as an error."""

from __future__ import annotations

import asyncio
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from open_webui import tasks as task_registry
from open_webui.models.automations import (
    AutomationForm,
    AutomationRuns,
    Automations,
    AutomationUpdateForm,
)
from open_webui.routers import automations as router
from open_webui.utils import automation_runner


class FinishStoppedTest(unittest.TestCase):
    def test_a_stopped_run_is_neither_an_error_nor_a_result(self):
        run = AutomationRuns.insert_run(f"task-{uuid.uuid4()}", status="running")
        automation_runner.record_report(run.id, "success", "Half done.")
        run = automation_runner.finish_run(run.id, stopped=True)
        self.assertEqual((run.status, run.error, run.summary), ("stopped", None, None))
        self.assertIsNotNone(run.finished_at)


class StreamTest(unittest.IsolatedAsyncioTestCase):
    """_stream_automation_chat with the chat pipeline replaced by a reply task."""

    async def _stream(self, reply, timeout_s=5.0, response=None):
        async def payload(request, form_data, user, metadata, model):
            return form_data, metadata, []

        async def respond(request, response, form_data, user, metadata, *rest):
            task_id, _ = task_registry.create_task(reply(metadata), id="chat-1")
            return {"task_id": task_id}

        with patch.object(automation_runner, "process_chat_payload", payload), patch.object(
            automation_runner, "chat_completion_handler", response or AsyncMock()
        ), patch.object(automation_runner, "process_chat_response", respond), patch.object(
            automation_runner, "begin_chat_trace"
        ), patch.object(automation_runner, "end_chat_trace"), patch(
            "open_webui.utils.chat_realtime.save_final_reply", AsyncMock()
        ):
            return await automation_runner._stream_automation_chat(
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
                timeout_s=timeout_s,
            )

    async def test_a_reply_that_finishes_is_not_stopped(self):
        async def reply(metadata):
            return None

        self.assertFalse(await self._stream(reply))

    async def test_a_reply_the_user_stopped_reports_stopped(self):
        # The reply loop catches its own cancellation and marks the metadata.
        async def reply(metadata):
            metadata["cancelled"] = True

        self.assertTrue(await self._stream(reply))

    async def test_a_reply_past_the_time_limit_is_cancelled(self):
        cancelled = asyncio.Event()

        async def reply(metadata):
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        with self.assertRaises(automation_runner.RunTimedOut):
            await self._stream(reply, timeout_s=0.05)
        self.assertTrue(cancelled.is_set())

    async def test_a_timeout_inside_the_run_is_not_the_time_limit(self):
        async def reply(metadata):
            return None

        with self.assertRaises(TimeoutError) as caught:
            await self._stream(reply, response=AsyncMock(side_effect=TimeoutError("provider")))
        self.assertNotIsInstance(caught.exception, automation_runner.RunTimedOut)


class ExecuteTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.owner = f"owner-{uuid.uuid4()}"
        self.automation = Automations.insert_new_automation(
            self.owner,
            AutomationForm(name="Daily map", prompt="Make the map.", model="m"),
        )
        self.addCleanup(Automations.delete_automation, self.automation.id)
        self.chat_id = f"chat-{uuid.uuid4()}"
        user = SimpleNamespace(id=self.owner, name="Owner", role="admin")
        patches = [
            patch.object(automation_runner.Users, "get_user_by_id", return_value=user),
            patch.object(automation_runner, "remember_catalog_model", return_value={"id": "m"}),
            patch.object(automation_runner, "check_usage_caps"),
            patch.object(
                automation_runner.Chats,
                "insert_new_chat",
                return_value=SimpleNamespace(id=self.chat_id),
            ),
            patch.object(automation_runner, "_notify_chat_created", AsyncMock()),
            patch.object(automation_runner, "notify_run", AsyncMock()),
            patch("open_webui.utils.chat_realtime.save_final_reply", AsyncMock()),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def _execute(self, stream, wait=True):
        with patch.object(automation_runner, "_stream_automation_chat", stream):
            return await automation_runner.execute_automation(
                MagicMock(), self.automation.id, "schedule", wait=wait
            )

    def _last_run(self):
        return AutomationRuns.get_runs(self.automation.id, limit=1)[0]

    async def test_a_scheduled_run_the_user_stopped(self):
        run = await self._execute(AsyncMock(return_value=True))
        self.assertEqual(run.status, "stopped")

    async def test_stopping_a_run_now_while_it_runs(self):
        started = asyncio.Event()

        async def stream(request, **kw):
            started.set()
            await asyncio.sleep(10)

        with patch.object(automation_runner, "_stream_automation_chat", stream):
            await automation_runner.execute_automation(
                MagicMock(), self.automation.id, self.owner, wait=False
            )
            await started.wait()
            # The Stop button cancels every task registered for the chat.
            for task_id in list(task_registry.list_task_ids_by_chat_id(self.chat_id)):
                await task_registry.stop_task(task_id)
        self.assertEqual(self._last_run().status, "stopped")

    async def test_a_run_past_its_time_limit_is_an_error(self):
        Automations.update_automation(
            self.automation.id, AutomationUpdateForm(timeout_minutes=5)
        )
        stream = AsyncMock(side_effect=automation_runner.RunTimedOut(300))
        with self.assertRaises(automation_runner.RunTimedOut):
            await self._execute(stream)
        run = self._last_run()
        self.assertEqual(run.status, "error")
        self.assertIn("5 minutes", run.error)
        self.assertEqual(stream.call_args.kwargs["timeout_s"], 300)

    async def test_the_default_time_limit(self):
        stream = AsyncMock(return_value=False)
        await self._execute(stream)
        self.assertEqual(
            stream.call_args.kwargs["timeout_s"],
            automation_runner.DEFAULT_RUN_TIMEOUT_MINUTES * 60,
        )


class TimeoutSettingTest(unittest.TestCase):
    def test_the_limit_must_be_between_a_minute_and_a_day(self):
        for bad in (0, -5, 1441):
            with self.subTest(minutes=bad), self.assertRaises(HTTPException):
                router._check_timeout(bad)
        for good in (None, 1, 60, 1440):
            router._check_timeout(good)


if __name__ == "__main__":
    unittest.main()
