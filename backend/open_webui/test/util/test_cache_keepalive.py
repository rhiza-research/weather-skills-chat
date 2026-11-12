"""While a tool batch runs, the turn's last model request is re-sent with no
output so the provider's prompt cache is read and outlives the batch."""

import asyncio
import copy
import json
import logging
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.responses import StreamingResponse

import main
import open_webui.utils.middleware as mw
from open_webui.models.usage import ORG_LIMIT_MESSAGE
from open_webui.routers import openai as openai_router
from open_webui.utils import chat, usage
from open_webui.utils import langfuse_tracing as lf

INTERVAL_S = mw.CACHE_KEEPALIVE_INTERVAL_S
TTL_S = mw.PROMPT_CACHE_TTL_S
FINISH_WAIT_S = mw.CACHE_KEEPALIVE_FINISH_WAIT_S


async def _until(condition, what):
    """Let the event loop and worker threads run until condition() holds."""
    deadline = time.monotonic() + 5
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.001)


class FakeClock:
    """A virtual clock: time moves only when the test advances it."""

    def __init__(self, start=1000.0):
        self.now_s = start
        self.sleepers = []  # [wake time, future]

    def now(self):
        return self.now_s

    async def sleep(self, delay):
        entry = [self.now_s + delay, asyncio.get_running_loop().create_future()]
        self.sleepers.append(entry)
        try:
            await entry[1]
        finally:
            if entry in self.sleepers:
                self.sleepers.remove(entry)

    def wakes(self):
        return sorted(wake for wake, fut in self.sleepers if not fut.done())

    async def wait_for_wake(self, wake):
        await _until(lambda: wake in self.wakes(), f"a sleeper waking at {wake}")

    def advance_to(self, when):
        """Move the clock to ``when`` and wake every sleeper due by then."""
        self.now_s = when
        for wake, fut in list(self.sleepers):
            if wake <= when and not fut.done():
                fut.set_result(None)


def _sse(*chunks):
    async def body():
        for chunk in chunks:
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(body(), media_type="text/event-stream")


def _tool_call_stream(call_id="call_1"):
    return _sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": call_id,
                                "function": {"name": "slow", "arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        }
    )


def _text_stream(text="Done."):
    return _sse({"choices": [{"delta": {"content": text}}]})


class ToolBatchKeepAliveTest(unittest.IsolatedAsyncioTestCase):
    """process_chat_response with a tool that runs until the test releases it."""

    async def asyncSetUp(self):
        self.events = []
        self.release = asyncio.Queue()
        self.tool_cancelled = False
        self.clock = FakeClock()
        self.order = []

        async def emit(event):
            self.events.append(event)

        async def slow():
            try:
                await self.release.get()
            except asyncio.CancelledError:
                self.tool_cancelled = True
                raise
            return "ok"

        self.metadata = {
            "chat_id": "chat-1",
            "message_id": "msg-1",
            "session_id": "sess-1",
            "function_calling": "native",
            "tools": {
                "slow": {
                    "spec": {"name": "slow", "parameters": {"properties": {}}},
                    "callable": slow,
                    "toolkit_id": "builtin",
                }
            },
        }
        self.form_data = {
            "model": "anthropic/claude-sonnet-4.5",
            "stream": True,
            "messages": [{"role": "user", "content": "Rain in Nairobi?"}],
            "tools": [{"type": "function", "function": {"name": "slow"}}],
        }
        self.user = SimpleNamespace(
            id="u1", email="u@example.com", name="U", role="user"
        )
        self.followup_at = []
        self.followup_streams = []

        async def followup(request, body, user):
            self.followup_at.append(self.clock.now())
            self.order.append("followup")
            if self.followup_streams:
                return self.followup_streams.pop(0)
            return _text_stream()

        self.followup = AsyncMock(side_effect=followup)
        self.keepalive_at = []

        async def keepalive(request, body, user):
            self.keepalive_at.append(self.clock.now())
            return {"choices": [{"message": {"content": "KEEPALIVE REPLY"}}]}

        self.keepalive = AsyncMock(side_effect=keepalive)
        self.applies = MagicMock(return_value=True)
        self.instances = []
        instances = self.instances

        class RecordingKeepAlive(mw.CacheKeepAlive):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                instances.append(self)

        patches = [
            patch.object(mw, "get_event_emitter", return_value=emit),
            patch.object(mw, "get_event_call", return_value=AsyncMock()),
            patch.object(
                mw,
                "Chats",
                MagicMock(
                    **{
                        "get_chat_by_id.return_value": SimpleNamespace(
                            chat={"title": "Title", "history": {"messages": {}}}
                        ),
                        "get_chat_revision.return_value": 1,
                        "get_message_by_id_and_message_id.return_value": {},
                    }
                ),
            ),
            patch.object(mw, "get_sorted_filter_ids", return_value=[]),
            patch.object(mw, "get_active_status_by_user_id", return_value=True),
            patch.object(mw, "generate_chat_completion", self.followup),
            patch.object(mw, "generate_cache_keepalive", self.keepalive),
            patch.object(mw, "cache_keepalive_applies", self.applies),
            patch.object(mw, "CacheKeepAlive", RecordingKeepAlive),
            patch.object(mw, "keepalive_clock", self.clock.now),
            patch.object(mw, "keepalive_sleep", self.clock.sleep),
            patch(
                "open_webui.utils.chat_realtime.save_final_reply",
                AsyncMock(return_value=1),
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.runs = []
        # Cleanups run last-registered first, so this ends the test's tasks
        # while the patches above are still in place.
        self.addAsyncCleanup(self._stop_tasks)

    async def _stop_tasks(self):
        """End every task the test started, even after a failed assertion."""
        tasks = [run for run in self.runs if not run.done()]
        tasks += [
            k._task
            for k in self.instances
            if k._task is not None and not k._task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=5)

    def _start(self, started_ago=0.0):
        """Run process_chat_response as a task; S is the first call's start."""
        heartbeat = mw.WaitingResponseHeartbeat(mw.get_event_emitter(self.metadata))
        self.S = self.clock.now() - started_ago
        run = asyncio.create_task(
            mw.process_chat_response(
                MagicMock(),
                _tool_call_stream(),
                self.form_data,
                self.user,
                self.metadata,
                {"id": "m"},
                [],
                {},
                detach=False,
                waiting_heartbeat=heartbeat,
                model_call_started_at=self.S,
            )
        )
        self.runs.append(run)
        return run

    async def _finish(self, run):
        done, _ = await asyncio.wait({run}, timeout=5)
        self.assertIn(run, done)
        run.result()

    def _final(self):
        return [
            e["data"]
            for e in self.events
            if e.get("type") == "chat:completion" and e["data"].get("done")
        ][-1]

    async def _keepalive_task_ends(self):
        await _until(lambda: self.instances, "a keep-alive")
        done, _ = await asyncio.wait({self.instances[-1]._task}, timeout=5)
        self.assertEqual(len(done), 1)

    async def test_long_batch_sends_one_keepalive_then_the_followup(self):
        run = self._start()
        await self.clock.wait_for_wake(self.S + INTERVAL_S)
        self.clock.advance_to(self.S + INTERVAL_S)
        await self.clock.wait_for_wake(self.S + 2 * INTERVAL_S)
        self.release.put_nowait(None)
        await self._finish(run)

        self.assertEqual(self.keepalive_at, [self.S + INTERVAL_S])
        # The turn's first request, as it was sent.
        self.assertIs(self.keepalive.await_args.args[1], self.form_data)
        self.assertEqual(self.followup.await_count, 1)
        self.assertNotIn("error", self._final())
        self.assertTrue(self.instances[0]._task.done())

    async def test_short_batch_sends_none(self):
        run = self._start()
        await self.clock.wait_for_wake(self.S + INTERVAL_S)
        self.release.put_nowait(None)
        await self._finish(run)

        self.keepalive.assert_not_awaited()
        self.assertEqual(self.followup.await_count, 1)
        self.assertEqual(self.clock.wakes(), [])

    async def test_very_long_batch_sends_one_per_interval(self):
        run = self._start()
        for n in (1, 2):
            await self.clock.wait_for_wake(self.S + n * INTERVAL_S)
            self.clock.advance_to(self.S + n * INTERVAL_S)
        await self.clock.wait_for_wake(self.S + 3 * INTERVAL_S)
        self.release.put_nowait(None)
        await self._finish(run)

        self.assertEqual(
            self.keepalive_at, [self.S + INTERVAL_S, self.S + 2 * INTERVAL_S]
        )

    async def test_late_start_sends_none(self):
        self.release.put_nowait(None)
        run = self._start(started_ago=TTL_S + 1)
        await self._finish(run)

        self.keepalive.assert_not_awaited()
        self.applies.assert_not_called()
        self.assertEqual(self.instances, [])
        self.assertEqual(self.followup.await_count, 1)

    async def test_request_past_the_interval_within_the_lifetime_is_kept_alive_at_once(self):
        run = self._start(started_ago=INTERVAL_S + 10)
        now = self.clock.now()
        await self.clock.wait_for_wake(now + INTERVAL_S)
        self.release.put_nowait(None)
        await self._finish(run)

        self.assertEqual(self.keepalive_at, [now])

    async def test_no_keepalive_once_the_lifetime_has_passed(self):
        run = self._start()
        await self.clock.wait_for_wake(self.S + INTERVAL_S)
        # The keep-alive wakes late, when the cache is already gone.
        self.clock.advance_to(self.S + TTL_S)
        await self._keepalive_task_ends()
        self.release.put_nowait(None)
        await self._finish(run)

        self.keepalive.assert_not_awaited()

    async def test_uncached_connection_sends_none(self):
        self.applies.return_value = False
        self.release.put_nowait(None)
        await self._finish(self._start())

        self.keepalive.assert_not_awaited()
        self.assertEqual(self.instances, [])
        self.assertEqual(self.applies.call_args.args[1], self.form_data["model"])

    async def test_without_native_function_calling_sends_none(self):
        del self.metadata["function_calling"]
        self.release.put_nowait(None)
        await self._finish(self._start())

        self.keepalive.assert_not_awaited()
        self.applies.assert_not_called()

    async def test_reply_holds_nothing_from_the_keepalive(self):
        run = self._start()
        await self.clock.wait_for_wake(self.S + INTERVAL_S)
        self.clock.advance_to(self.S + INTERVAL_S)
        await _until(lambda: self.keepalive.await_count, "the keep-alive")
        self.release.put_nowait(None)
        await self._finish(run)

        self.assertNotIn("KEEPALIVE REPLY", json.dumps(self.events, default=str))
        followup_body = self.followup.await_args.args[1]
        self.assertNotIn("KEEPALIVE REPLY", json.dumps(followup_body, default=str))

    async def _failing_batch(self):
        run = self._start()
        await self.clock.wait_for_wake(self.S + INTERVAL_S)
        self.clock.advance_to(self.S + INTERVAL_S)
        await self._keepalive_task_ends()
        self.assertEqual(self.clock.wakes(), [])
        self.release.put_nowait(None)
        await self._finish(run)

        self.assertEqual(self.keepalive.await_count, 1)
        self.assertEqual(self.followup.await_count, 1)
        self.assertEqual(self._final()["content"].count("Done."), 1)
        self.assertNotIn("error", self._final())

    async def test_a_usage_limit_stops_keepalives_for_the_batch_at_info(self):
        self.keepalive.side_effect = HTTPException(429, detail=ORG_LIMIT_MESSAGE)
        with self.assertLogs(mw.log, level="INFO") as logs:
            await self._failing_batch()

        records = [r for r in logs.records if "Cache keep-alive" in r.getMessage()]
        self.assertEqual([r.levelno for r in records], [logging.INFO])
        self.assertIsNone(records[0].exc_info)

    async def test_other_failures_stop_keepalives_for_the_batch_with_a_warning(self):
        self.keepalive.side_effect = HTTPException(503, detail="provider down")
        with self.assertLogs(mw.log, level="WARNING") as logs:
            await self._failing_batch()

        self.assertTrue(any("Cache keep-alive failed" in line for line in logs.output))

    async def test_an_error_reply_stops_keepalives_for_the_batch(self):
        send = AsyncMock(return_value={"error": {"message": "overloaded"}})
        with patch.object(mw, "generate_cache_keepalive", chat.generate_cache_keepalive), patch.object(
            chat, "authorize_model_call", return_value=lf.MODEL_CALL_TRACING_APP
        ), patch.object(chat, "send_cache_keepalive", send), patch.object(
            chat, "bind_usage_to_response", AsyncMock()
        ):
            run = self._start()
            await self.clock.wait_for_wake(self.S + INTERVAL_S)
            self.clock.advance_to(self.S + INTERVAL_S)
            await self._keepalive_task_ends()
            self.assertEqual(self.clock.wakes(), [])
            self.release.put_nowait(None)
            await self._finish(run)

        send.assert_awaited_once()
        self.assertEqual(self.followup.await_count, 1)
        self.assertNotIn("error", self._final())

    async def test_tool_completion_waits_for_a_keepalive_in_flight(self):
        gate = asyncio.Event()

        async def keepalive(request, body, user):
            self.keepalive_at.append(self.clock.now())
            await gate.wait()
            self.order.append("keepalive")

        self.keepalive.side_effect = keepalive
        run = self._start()
        await self.clock.wait_for_wake(self.S + INTERVAL_S)
        self.clock.advance_to(self.S + INTERVAL_S)
        await _until(lambda: self.keepalive_at, "the keep-alive")
        self.release.put_nowait(None)
        # finish() is waiting, bounded by its timer.
        await self.clock.wait_for_wake(self.S + INTERVAL_S + FINISH_WAIT_S)
        self.followup.assert_not_awaited()
        gate.set()
        await self._finish(run)

        self.assertEqual(self.order, ["keepalive", "followup"])
        self.assertEqual(self.clock.wakes(), [])

    async def test_a_stalled_keepalive_is_cancelled_after_the_finish_wait(self):
        cancelled = asyncio.Event()

        async def keepalive(request, body, user):
            self.keepalive_at.append(self.clock.now())
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        self.keepalive.side_effect = keepalive
        run = self._start()
        await self.clock.wait_for_wake(self.S + INTERVAL_S)
        self.clock.advance_to(self.S + INTERVAL_S)
        await _until(lambda: self.keepalive_at, "the keep-alive")
        self.release.put_nowait(None)
        deadline = self.S + INTERVAL_S + FINISH_WAIT_S
        await self.clock.wait_for_wake(deadline)
        self.followup.assert_not_awaited()
        self.clock.advance_to(deadline)
        await self._finish(run)

        self.assertTrue(cancelled.is_set())
        self.assertEqual(self.followup_at, [deadline])

    async def test_next_batch_keeps_the_followup_request_alive(self):
        self.followup_streams = [_tool_call_stream("call_2")]
        run = self._start()
        await self.clock.wait_for_wake(self.S + INTERVAL_S)
        self.clock.advance_to(self.S + INTERVAL_S)
        await _until(lambda: self.keepalive.await_count == 1, "the first keep-alive")
        self.release.put_nowait(None)
        # The first keep-alive's next sleep also wakes at S + 2 * INTERVAL_S, so
        # wait for the second batch's own keep-alive before looking for it.
        await _until(lambda: len(self.instances) == 2, "the second batch's keep-alive")
        self.assertTrue(self.instances[0]._task.done())
        # The follow-up is sent at S + INTERVAL_S and starts the second batch.
        followup_start = self.S + INTERVAL_S
        await self.clock.wait_for_wake(followup_start + INTERVAL_S)
        self.clock.advance_to(followup_start + INTERVAL_S)
        await _until(lambda: self.keepalive.await_count == 2, "the second keep-alive")
        self.release.put_nowait(None)
        await self._finish(run)

        self.assertEqual(self.followup.await_count, 2)
        self.assertEqual(self.followup_at[0], followup_start)
        self.assertEqual(
            self.keepalive_at, [self.S + INTERVAL_S, followup_start + INTERVAL_S]
        )
        self.assertIs(self.keepalive.await_args_list[0].args[1], self.form_data)
        self.assertIs(
            self.keepalive.await_args_list[1].args[1],
            self.followup.await_args_list[0].args[1],
        )
        self.assertTrue(all(k._task.done() for k in self.instances))

    async def test_stop_cancels_the_keepalive(self):
        cancelled = asyncio.Event()

        async def keepalive(request, body, user):
            self.keepalive_at.append(self.clock.now())
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        self.keepalive.side_effect = keepalive
        run = self._start()
        await self.clock.wait_for_wake(self.S + INTERVAL_S)
        self.clock.advance_to(self.S + INTERVAL_S)
        await _until(lambda: self.keepalive_at, "the keep-alive")
        run.cancel()
        await asyncio.wait({run}, timeout=5)

        self.assertTrue(cancelled.is_set())
        self.assertTrue(self.tool_cancelled)
        self.assertTrue(self.metadata["cancelled"])
        self.followup.assert_not_awaited()
        self.assertTrue(any(e.get("type") == "task-cancelled" for e in self.events))

    async def test_a_tool_batch_that_raises_leaves_no_keepalive_running(self):
        with patch.object(mw, "execution_waves", side_effect=RuntimeError("boom")):
            await self._finish(self._start())

        self.assertEqual(len(self.instances), 1)
        self.assertTrue(self.instances[0]._task.done())
        self.assertEqual(self.clock.wakes(), [])
        self.keepalive.assert_not_awaited()
        self.assertIn("error", self._final())


class CacheKeepAliveCancelTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_stops_a_waiting_keepalive(self):
        clock = FakeClock()
        send = AsyncMock()
        with patch.object(mw, "keepalive_clock", clock.now), patch.object(
            mw, "keepalive_sleep", clock.sleep
        ):
            keepalive = mw.CacheKeepAlive(send, {}, clock.now())
            keepalive.start()
            try:
                await clock.wait_for_wake(clock.now() + INTERVAL_S)
            finally:
                await keepalive.cancel()
        send.assert_not_awaited()
        self.assertTrue(keepalive._task.done())
        self.assertEqual(clock.wakes(), [])


class FirstCallStartTimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_run_chat_job_passes_the_first_calls_start_time(self):
        seen = {}

        async def payload(request, form_data, user, metadata, model):
            return form_data, metadata, []

        async def respond(*args, **kw):
            seen.update(kw)

        prepared = main.PreparedChat(
            model={"id": "m"},
            metadata={"organization_id": "org-1"},
            direct=False,
            tasks=None,
            turn=None,
        )
        user = SimpleNamespace(id="u1", email="u1@example.com", name="U", role="user")
        with patch.object(main, "prepare_chat_completion", return_value=prepared), patch.object(
            main, "process_chat_payload", payload
        ), patch.object(main, "chat_completion_handler", AsyncMock()), patch.object(
            main, "process_chat_response", respond
        ), patch.object(main, "get_event_emitter", return_value=None), patch.object(
            main, "LANGFUSE_ENABLED", False
        ):
            await main.chat_completion(
                SimpleNamespace(state=SimpleNamespace()), {"model": "m"}, user, "org-1"
            )

        self.assertIsInstance(seen["model_call_started_at"], float)


OPENROUTER = "https://openrouter.ai/api/v1"
MODEL = "anthropic/claude-sonnet-4.5"
COMPLETION = {
    "choices": [{"message": {"content": ""}}],
    "usage": {
        "prompt_tokens": 780000,
        "completion_tokens": 0,
        "prompt_tokens_details": {"cached_tokens": 780000},
        "cost": 0.16,
    },
}


class _FakeResponse:
    def __init__(self, status=200, body=None):
        self.status = status
        self.body = body
        self.headers = {"Content-Type": "application/json"}

    async def json(self):
        if self.body is not None:
            return self.body
        if self.status >= 400:
            return {"error": {"message": "upstream failed"}}
        return COMPLETION

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def close(self):
        pass


class _FakeSession:
    def __init__(self, test):
        self.test = test

    async def request(self, **kwargs):
        self.test.sent.append(json.loads(kwargs["data"]))
        self.test.entered.set()
        if self.test.block:
            await asyncio.Event().wait()
        if self.test.replies:
            return self.test.replies.pop(0)
        return _FakeResponse()

    async def close(self):
        pass


def _request(url=OPENROUTER, style=None, api_config=None):
    config = SimpleNamespace(
        OPENAI_API_BASE_URLS=[url],
        OPENAI_API_KEYS=["key"],
        OPENAI_API_CONFIGS={
            "0": api_config or ({"model_call_tracing": style} if style else {})
        },
    )
    models = {
        MODEL: {"id": MODEL, "owned_by": "openai"},
        "weather-agent": {"id": "weather-agent", "owned_by": "openai"},
        "openai/gpt-4o": {"id": "openai/gpt-4o", "owned_by": "openai"},
    }
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=config, MODELS=models)),
        state=SimpleNamespace(),
        headers={},
    )


def _body():
    return {
        "model": MODEL,
        "stream": True,
        "stream_options": {"include_usage": True},
        "tools": [
            {
                "type": "function",
                "function": {"name": "dynamical_fetch", "parameters": {}},
            }
        ],
        "messages": [
            {"role": "system", "content": "You are a weather assistant."},
            {"role": "user", "content": "Rain in Nairobi next week?"},
        ],
        "metadata": {
            "chat_id": "chat-1",
            "message_id": "msg-1",
            "organization_id": "org-1",
            "user_id": "u1",
            "usage_source": "chat",
        },
    }


class KeepAliveCallTest(unittest.IsolatedAsyncioTestCase):
    """chat.generate_cache_keepalive through the OpenAI router."""

    async def asyncSetUp(self):
        self._reset_tracing()
        self.addCleanup(self._reset_tracing)
        self.root = MagicMock(trace_id="c" * 32, id="d" * 16)
        lf._trace_var.set(self.root)
        lf._trace_metadata_var.set({"chat_id": "chat-1", "message_id": "msg-1"})
        openai_router._provider_down_until.clear()
        self.addCleanup(openai_router._provider_down_until.clear)
        self.user = SimpleNamespace(
            id="u1", email="u@example.com", name="U", role="admin"
        )
        self.sent = []
        self.replies = []
        self.block = False
        self.entered = asyncio.Event()
        self.recorded = []
        self.model_row = None
        self.caps = MagicMock()
        self.patches = [
            patch.object(lf, "tracing_enabled", return_value=True),
            patch.object(chat, "tracing_enabled", return_value=True),
            patch.object(openai_router, "tracing_enabled", return_value=True),
            patch.object(
                openai_router.Models,
                "get_model_by_id",
                side_effect=lambda model_id: self.model_row,
            ),
            patch(
                "open_webui.models.organizations.Organizations.user_organization_ids",
                return_value=["org-1"],
            ),
            patch("open_webui.utils.catalog.is_usable", return_value=True),
            patch.object(
                openai_router.aiohttp,
                "ClientSession",
                side_effect=lambda **kwargs: _FakeSession(self),
            ),
            patch.object(chat, "enforce_usage_caps", self.caps),
            patch.object(
                usage,
                "record_provider_usage",
                side_effect=lambda u, context: self.recorded.append((u, context)),
            ),
            patch.object(openai_router, "PROVIDER_RETRY_DELAY_S", 0),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.tasks = []
        # Cleanups run last-registered first, so this ends the test's tasks
        # while the patches above are still in place.
        self.addAsyncCleanup(self._stop_tasks)

    @staticmethod
    def _reset_tracing():
        lf._trace_var.set(None)
        lf._trace_metadata_var.set(None)
        lf._generation_stack_var.set(None)

    async def _stop_tasks(self):
        pending = [task for task in self.tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=5)

    def _names(self):
        return [
            call.kwargs.get("name") for call in self.root.start_observation.call_args_list
        ]

    async def test_sends_the_same_request_with_no_output(self):
        await chat.generate_chat_completion(_request(), _body(), self.user)
        body = _body()
        before = copy.deepcopy(body)
        await chat.generate_cache_keepalive(_request(), body, self.user)

        normal, keepalive = self.sent
        self.assertIs(keepalive["stream"], False)
        self.assertEqual(keepalive["max_tokens"], 0)
        self.assertNotIn("stream_options", keepalive)
        self.assertNotIn("max_tokens", normal)
        skip = ("stream", "stream_options", "max_tokens")
        self.assertEqual(
            {k: v for k, v in keepalive.items() if k not in skip},
            {k: v for k, v in normal.items() if k not in skip},
        )
        self.assertEqual(keepalive["messages"], normal["messages"])
        self.assertEqual(keepalive["tools"], normal["tools"])
        self.assertEqual(body, before)

    async def test_the_models_output_limit_is_overridden(self):
        self.model_row = SimpleNamespace(
            base_model_id=None,
            params=SimpleNamespace(model_dump=lambda: {"max_tokens": 4096}),
            meta=None,
        )
        body = _body()
        body["max_completion_tokens"] = 2048
        await chat.generate_cache_keepalive(_request(), body, self.user)

        self.assertEqual(self.sent[0]["max_tokens"], 0)
        self.assertNotIn("max_completion_tokens", self.sent[0])

    async def test_access_check_and_request_build_use_the_turns_bypass_filter(self):
        with patch.object(
            chat, "authorize_model_call", wraps=chat.authorize_model_call
        ) as authorize, patch.object(
            openai_router, "prepare_provider_call", wraps=openai_router.prepare_provider_call
        ) as prepare:
            await chat.generate_cache_keepalive(_request(), _body(), self.user)
            await chat.generate_cache_keepalive(
                _request(), _body(), self.user, bypass_filter=True
            )

        self.assertEqual([c.args[3] for c in authorize.call_args_list], [False, True])
        self.assertEqual([c.args[3] for c in prepare.call_args_list], [False, True])

    async def test_usage_is_recorded_as_a_keepalive_and_counts_toward_caps(self):
        await chat.generate_cache_keepalive(_request(), _body(), self.user)

        self.caps.assert_called_once()
        self.assertEqual(len(self.recorded), 1)
        recorded_usage, context = self.recorded[0]
        self.assertEqual(context["source"], "cache_keepalive")
        self.assertEqual(context["chat_id"], "chat-1")
        self.assertEqual(recorded_usage["cost"], 0.16)

    async def test_app_traced_call_is_a_cache_keepalive_generation(self):
        await chat.generate_cache_keepalive(_request(), _body(), self.user)

        kwargs = self.root.start_observation.call_args.kwargs
        self.assertEqual(kwargs["name"], "cache-keepalive")
        self.assertEqual(kwargs["as_type"], "generation")
        self.assertNotIn("llm", self._names())

    async def test_provider_traced_call_is_named_cache_keepalive(self):
        await chat.generate_cache_keepalive(
            _request(style="openrouter"), _body(), self.user
        )

        self.assertEqual(self.sent[0]["trace"]["generation_name"], "cache-keepalive")
        self.root.start_observation.assert_not_called()

    async def test_cancelled_mid_call_ends_its_generation_and_leaves_the_parents(self):
        parent = MagicMock()
        lf._generation_stack().append(parent)
        self.block = True
        task = asyncio.create_task(
            chat.generate_cache_keepalive(_request(), _body(), self.user)
        )
        self.tasks.append(task)
        await asyncio.wait_for(self.entered.wait(), timeout=5)
        task.cancel()
        await asyncio.wait({task}, timeout=5)

        self.assertTrue(task.cancelled())
        self.assertEqual(self._names(), ["cache-keepalive"])
        generation = self.root.start_observation.return_value
        self.assertEqual(generation.update.call_args.kwargs["level"], "ERROR")
        generation.end.assert_called_once()
        parent.end.assert_not_called()
        parent.update.assert_not_called()
        self.assertEqual(lf._generation_stack(), [parent])

    async def test_a_cap_refuses_the_keepalive_before_sending(self):
        self.caps.side_effect = HTTPException(429, detail=ORG_LIMIT_MESSAGE)
        with self.assertRaises(HTTPException):
            await chat.generate_cache_keepalive(_request(), _body(), self.user)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.recorded, [])

    async def test_an_error_reply_raises(self):
        self.replies = [_FakeResponse(200, {"error": {"message": "overloaded"}})]
        with self.assertRaisesRegex(Exception, "overloaded"):
            await chat.generate_cache_keepalive(_request(), _body(), self.user)
        self.assertEqual(len(self.sent), 1)

    async def test_a_reply_that_is_not_a_completion_raises(self):
        with patch.object(chat, "send_cache_keepalive", AsyncMock(return_value="text")):
            with self.assertRaisesRegex(Exception, "not a completion"):
                await chat.generate_cache_keepalive(_request(), _body(), self.user)
        self.assertEqual(self.recorded, [])

    async def test_an_unexpected_stream_is_closed_and_raises(self):
        async def body():
            yield b"data: {}\n\n"

        cleanup = AsyncMock()
        stream = StreamingResponse(body(), media_type="text/event-stream")
        stream.background = cleanup
        with patch.object(chat, "send_cache_keepalive", AsyncMock(return_value=stream)):
            with self.assertRaisesRegex(Exception, "not a completion"):
                await chat.generate_cache_keepalive(_request(), _body(), self.user)
        cleanup.assert_awaited_once()

    async def test_a_failure_has_no_retry_backup_or_down_marker(self):
        self.model_row = SimpleNamespace(
            base_model_id=None,
            params=SimpleNamespace(model_dump=lambda: {}),
            meta=SimpleNamespace(fallback_model_id="requesty.anthropic/claude-sonnet-4-5"),
        )
        self.replies = [_FakeResponse(503)]
        with self.assertRaises(HTTPException):
            await chat.generate_cache_keepalive(
                _request(style="openrouter"), _body(), self.user
            )

        self.assertEqual(len(self.sent), 1)
        self.assertEqual(openai_router._provider_down_until, {})
        self.assertEqual(self._names(), ["cache-keepalive"])
        self.assertEqual(
            self.root.start_observation.call_args.kwargs["level"], "ERROR"
        )


class PromptCachingAppliesTest(unittest.TestCase):
    def setUp(self):
        self.model_row = None
        patcher = patch.object(
            openai_router.Models,
            "get_model_by_id",
            side_effect=lambda model_id: self.model_row,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        openai_router._provider_down_until.clear()
        self.addCleanup(openai_router._provider_down_until.clear)

    def _with_backup(self):
        self.model_row = SimpleNamespace(
            base_model_id=MODEL,
            meta=SimpleNamespace(fallback_model_id="requesty.anthropic/claude-sonnet-4-5"),
        )

    def test_openrouter_anthropic_model(self):
        self.assertTrue(chat.cache_keepalive_applies(_request(), MODEL))

    def test_openrouter_other_model(self):
        self.assertFalse(chat.cache_keepalive_applies(_request(), "openai/gpt-4o"))

    def test_other_provider(self):
        request = _request(url="https://api.anthropic.com/v1")
        self.assertFalse(chat.cache_keepalive_applies(request, MODEL))

    def test_empty_url(self):
        self.assertFalse(openai_router.prompt_caching_applies(_request(url=""), MODEL))

    def test_no_connection_serves_the_model(self):
        request = _request(api_config={"model_ids": ["openai/gpt-4o"]})
        self.assertIsNone(openai_router.connection_index_for_model(request, MODEL))
        self.assertFalse(openai_router.prompt_caching_applies(request, MODEL))

    def test_the_connection_prefix_is_stripped(self):
        request = _request(api_config={"prefix_id": "or"})
        self.assertTrue(openai_router.prompt_caching_applies(request, f"or.{MODEL}"))
        self.assertFalse(
            openai_router.prompt_caching_applies(request, "or.openai/gpt-4o")
        )

    def test_wrapper_model_forwarding_to_anthropic(self):
        self.model_row = SimpleNamespace(base_model_id=MODEL, meta=None)
        self.assertTrue(chat.cache_keepalive_applies(_request(), "weather-agent"))

    def test_direct_and_ollama_models(self):
        request = _request()
        request.state.direct = True
        self.assertFalse(chat.cache_keepalive_applies(request, MODEL))
        request = _request()
        request.app.state.MODELS[MODEL]["owned_by"] = "ollama"
        self.assertFalse(chat.cache_keepalive_applies(request, MODEL))

    def test_a_reply_on_its_backup(self):
        self._with_backup()
        request = _request()
        request.state.provider_backups = {"weather-agent"}
        self.assertFalse(chat.cache_keepalive_applies(request, "weather-agent"))

    def test_a_down_provider_for_a_model_with_a_backup(self):
        self._with_backup()
        openai_router._provider_down_until[OPENROUTER] = time.monotonic() + 60
        self.assertFalse(chat.cache_keepalive_applies(_request(), "weather-agent"))
        openai_router._provider_down_until[OPENROUTER] = 0.0
        self.assertTrue(chat.cache_keepalive_applies(_request(), "weather-agent"))

    def test_an_unexpected_error_is_logged_at_warning(self):
        with patch.object(
            chat, "prompt_caching_applies", side_effect=RuntimeError("db down")
        ), self.assertLogs(chat.log, level="WARNING"):
            self.assertFalse(chat.cache_keepalive_applies(_request(), MODEL))


class SharedCachePredicateTest(unittest.TestCase):
    def test_marking_matches_the_predicate(self):
        for url, model, marked in [
            (OPENROUTER, MODEL, True),
            (OPENROUTER, "openai/gpt-4o", False),
            ("https://api.anthropic.com/v1", MODEL, False),
        ]:
            with self.subTest(url=url, model=model):
                payload = openai_router.enable_openrouter_prompt_caching(
                    url, {"model": model, "messages": []}
                )
                self.assertEqual("cache_control" in payload, marked)
                self.assertEqual(
                    openai_router.marks_anthropic_prompt_cache(url, model), marked
                )


if __name__ == "__main__":
    unittest.main()
