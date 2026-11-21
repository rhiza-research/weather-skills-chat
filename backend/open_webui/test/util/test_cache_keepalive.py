"""A chat's prompt cache is kept alive between its model calls."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from open_webui.routers import openai as openai_router
from open_webui.utils import cache_keepalive


class TimerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reply_running = False
        patches = [
            patch.object(cache_keepalive, "INTERVAL_S", 0.001),
            patch.object(cache_keepalive, "IDLE_COUNT", 3),
            patch.object(
                cache_keepalive,
                "list_task_ids_by_chat_id",
                lambda chat_id: ["reply"] if self.reply_running else [],
            ),
            patch.dict(cache_keepalive._timers, clear=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addAsyncCleanup(self._cancel_timers)

    async def _cancel_timers(self):
        timers = list(cache_keepalive._timers.values())
        for timer in timers:
            timer.cancel()
        if timers:
            await asyncio.wait(timers, timeout=2)

    async def _ends(self, timer):
        done, _ = await asyncio.wait({timer}, timeout=2)
        self.assertIn(timer, done)

    async def test_after_the_reply_it_sends_the_idle_count_then_stops(self):
        send = AsyncMock()
        cache_keepalive.restart("chat-1", send, "chat")
        await self._ends(cache_keepalive._timers["chat-1"])

        self.assertEqual(send.await_count, 3)
        self.assertNotIn("chat-1", cache_keepalive._timers)

    async def test_while_the_reply_runs_there_is_no_limit(self):
        self.reply_running = True
        sent = []

        async def send():
            sent.append(1)
            if len(sent) == 5:
                self.reply_running = False

        cache_keepalive.restart("chat-1", send, "chat")
        await self._ends(cache_keepalive._timers["chat-1"])

        self.assertEqual(len(sent), 5 + 3)

    async def test_a_scheduled_run_gets_none_once_it_ends(self):
        send = AsyncMock()
        cache_keepalive.restart("chat-1", send, "automation")
        await self._ends(cache_keepalive._timers["chat-1"])

        send.assert_not_awaited()

    async def test_the_chats_next_call_replaces_its_timer(self):
        self.reply_running = True
        first, second = AsyncMock(), AsyncMock()
        cache_keepalive.restart("chat-1", first, "chat")
        old = cache_keepalive._timers["chat-1"]
        cache_keepalive.restart("chat-1", second, "chat")
        await self._ends(old)

        self.assertTrue(old.cancelled())
        self.assertIsNot(cache_keepalive._timers["chat-1"], old)

    async def test_a_call_without_cache_markers_stops_the_chats_timer(self):
        cache_keepalive.restart("chat-1", AsyncMock(), "chat")
        old = cache_keepalive._timers["chat-1"]
        cache_keepalive.restart("chat-1", None, "chat")
        await self._ends(old)

        self.assertEqual(cache_keepalive._timers, {})

    async def test_a_failure_ends_the_timer(self):
        send = AsyncMock(side_effect=HTTPException(503, detail="down"))
        with self.assertLogs(cache_keepalive.log, level="WARNING"):
            cache_keepalive.restart("chat-1", send, "chat")
            await self._ends(cache_keepalive._timers["chat-1"])

        send.assert_awaited_once()


USAGE = {"organization_id": "org-1", "user_id": "u1", "source": "chat", "chat_id": "chat-1"}
USER = SimpleNamespace(id="u1", name="U", email="u@example.com", role="user")


def _call(**fields):
    payload = {
        "model": "anthropic/claude-sonnet-4.5",
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_completion_tokens": 4096,
        "messages": [{"role": "user", "content": "Rain in Nairobi?"}],
        "cache_control": {"type": "ephemeral"},
        "trace": {"generation_name": "llm"},
    }
    return openai_router.ProviderCall(
        "https://router.example.com/v1",
        "sk-test-key",
        json.dumps(payload),
        "chat-1",
        0,
        None,
        "router",
        **{"reply_usage": USAGE, "cached": True, **fields},
    )


class SendHookTest(unittest.IsolatedAsyncioTestCase):
    async def _send(self, call):
        """Start the call; the provider is unreachable, so it fails after the hook."""
        with patch.object(cache_keepalive, "restart") as restart, patch.object(
            openai_router.aiohttp, "ClientSession", side_effect=RuntimeError("offline")
        ):
            with self.assertRaises(HTTPException):
                await openai_router._send_provider_call(call, USER)
        return restart

    async def test_a_reply_call_is_kept_alive_with_the_same_request_and_no_output(self):
        restart = await self._send(_call())
        chat_id, send, source = restart.call_args.args
        self.assertEqual((chat_id, source), ("chat-1", "chat"))

        provider = AsyncMock(return_value={"usage": {"prompt_tokens": 10}})
        record = AsyncMock()
        with patch.object(openai_router, "_send_provider_call", provider), patch.object(
            openai_router, "bind_usage_to_response", record
        ):
            await send()

        sent = provider.await_args.args[0]
        body = json.loads(sent.payload)
        self.assertEqual(body["messages"], [{"role": "user", "content": "Rain in Nairobi?"}])
        self.assertEqual((body["stream"], body["max_tokens"]), (False, 0))
        self.assertNotIn("stream_options", body)
        self.assertNotIn("max_completion_tokens", body)
        self.assertEqual(body["trace"]["generation_name"], "cache-keepalive")
        self.assertEqual(sent.url, "https://router.example.com/v1")
        # The keep-alive itself never restarts the chat's timer.
        self.assertIsNone(sent.reply_usage)
        self.assertEqual(record.await_args.args[1]["source"], "cache_keepalive")
        self.assertEqual(record.await_args.args[1]["chat_id"], "chat-1")

    async def test_a_call_without_cache_markers_stops_the_chats_timer(self):
        restart = await self._send(_call(cached=False))
        self.assertIsNone(restart.call_args.args[1])

    async def test_a_task_call_leaves_the_chats_timer_alone(self):
        restart = await self._send(_call(reply_usage=None))
        restart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
