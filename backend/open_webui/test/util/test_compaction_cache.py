"""Compaction's summary call re-sends the reply's warm last call to read its cache."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from open_webui.routers import openai as openai_router
from open_webui.utils import cache_keepalive
from open_webui.utils import chat_compaction as cc

FINAL = "Here is the rainfall map."


def _call(message_id="a1", model="anthropic/claude-opus-5-5"):
    payload = {
        "model": model,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": 64000,
        "messages": [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "plot rain"},
        ],
        "tools": [{"type": "function", "function": {"name": "run"}}],
    }
    return MagicMock(
        payload=json.dumps(payload),
        reply_usage={"message_id": message_id, "organization_id": "o", "user_id": "u"},
        chat_id="c",
    )


CHAIN = [
    {"role": "user", "content": "plot rain"},
    {"role": "assistant", "content": FINAL},
]


class ReusePayloadTest(unittest.TestCase):
    def test_the_last_call_gets_the_final_reply_and_the_instructions(self):
        payload, share = cc._reuse_payload(CHAIN, "a1", (_call(), None))
        body = json.loads(payload)
        self.assertEqual(body["messages"][1], {"role": "user", "content": "plot rain"})
        self.assertEqual(body["messages"][2], {"role": "assistant", "content": FINAL})
        self.assertEqual(body["messages"][3]["content"], cc.CACHED_INSTRUCTIONS)
        self.assertEqual(body["tools"][0]["function"]["name"], "run")
        self.assertIs(body["stream"], False)
        self.assertEqual(body["max_tokens"], cc.SUMMARY_MAX_TOKENS)
        self.assertNotIn("stream_options", body)
        self.assertTrue(0 < share < 1)

    def test_another_reply_or_no_warm_call_is_sent_fresh(self):
        self.assertIsNone(cc._reuse_payload(CHAIN, "a1", (_call("other"), None))[0])
        self.assertIsNone(cc._reuse_payload(CHAIN, "a1", None)[0])

    def test_a_reply_that_ended_in_a_tool_call_is_sent_fresh(self):
        chain = [CHAIN[0], {"role": "assistant", "content": "", "tool_calls": [{"id": "t"}]}]
        self.assertIsNone(cc._reuse_payload(chain, "a1", (_call(), None))[0])


class SummarizeTest(unittest.IsolatedAsyncioTestCase):
    def _started(self, payload):
        usage = {"context_used": 900_000, "context_window": 1_000_000}
        return cc.Started([], usage, {}, "FRESH", payload, 0.8)

    async def test_the_reused_request_is_sent_on_the_calls_connection(self):
        reply = {
            "choices": [{"message": {"content": "S"}}],
            "usage": {"prompt_tokens": 900_000, "completion_tokens": 2_000},
        }
        send = AsyncMock(return_value=reply)
        with patch.object(openai_router, "send_after_call", new=send), patch.object(
            cc, "_call_model", new=AsyncMock()
        ) as fresh:
            summary, estimate = await cc._summarize(
                MagicMock(), MagicMock(), "m", self._started("P"), {}, (_call(), MagicMock())
            )
        self.assertEqual(summary, "S")
        self.assertEqual(send.await_args.args[2], "P")
        fresh.assert_not_called()
        # 900k - 0.8 x 900k + 2k
        self.assertEqual(estimate["context_estimate"], 182_000)

    async def test_a_tool_call_instead_of_a_summary_falls_back_to_fresh(self):
        reply = {"choices": [{"message": {"content": "", "tool_calls": [{"id": "t"}]}}]}
        fresh = AsyncMock(return_value=("S", {"prompt_tokens": 10, "completion_tokens": 1}))
        with patch.object(openai_router, "send_after_call", new=AsyncMock(return_value=reply)), patch.object(
            cc, "_call_model", new=fresh
        ):
            summary, _ = await cc._summarize(
                MagicMock(), MagicMock(), "m", self._started("P"), {}, (_call(), MagicMock())
            )
        self.assertEqual(summary, "S")
        self.assertEqual(fresh.await_args.args[3]["messages"][0]["content"], "FRESH")

    async def test_without_a_warm_call_it_is_sent_fresh(self):
        fresh = AsyncMock(return_value=("S", {"prompt_tokens": 10, "completion_tokens": 1}))
        with patch.object(cc, "_call_model", new=fresh):
            await cc._summarize(MagicMock(), MagicMock(), "m", self._started(None), {"task": "t"}, None)
        self.assertEqual(fresh.await_args.args[3]["metadata"], {"task": "t"})


class CompactChatWarmCallTest(unittest.IsolatedAsyncioTestCase):
    async def test_another_users_cached_request_is_not_reused(self):
        start = MagicMock(return_value=None)
        other = MagicMock(id="someone-else")
        with patch.object(cache_keepalive, "warm_call", return_value=(_call(), other)), patch.object(
            cc, "_start_compaction", new=start
        ), patch.object(cc, "_emit", new=AsyncMock()):
            await cc.compact_chat(
                MagicMock(), MagicMock(id="u"), chat_id="c", message_id="a1", model_id="m", emitter_meta={}
            )
        self.assertIsNone(start.call_args.args[4])


class WarmCallTest(unittest.TestCase):
    def tearDown(self):
        cache_keepalive._last_calls.clear()

    def test_the_last_call_is_warm_until_its_cache_would_expire(self):
        with patch.object(cache_keepalive.time, "monotonic", return_value=1000.0):
            cache_keepalive.restart("c", None, "chat", last_call=("CALL", "USER"))
        with patch.object(cache_keepalive.time, "monotonic", return_value=1200.0):
            self.assertEqual(cache_keepalive.warm_call("c"), ("CALL", "USER"))
            cache_keepalive.touch("c")
        with patch.object(cache_keepalive.time, "monotonic", return_value=1450.0):
            self.assertEqual(cache_keepalive.warm_call("c"), ("CALL", "USER"))
        with patch.object(cache_keepalive.time, "monotonic", return_value=1500.0):
            self.assertIsNone(cache_keepalive.warm_call("c"))

    def test_an_uncached_call_replaces_it(self):
        cache_keepalive.restart("c", None, "chat", last_call=("CALL", "USER"))
        cache_keepalive.restart("c", None, "chat")
        self.assertIsNone(cache_keepalive.warm_call("c"))


class SendAfterCallTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_spending_limit_stops_it(self):
        from open_webui.utils import usage as usage_utils

        send = AsyncMock()
        with patch.object(usage_utils, "check_usage_caps", side_effect=RuntimeError("limit")), patch.object(
            openai_router, "_send_provider_call", new=send
        ):
            with self.assertRaises(RuntimeError):
                await openai_router.send_after_call(_call(), MagicMock(), "{}", "task")
        send.assert_not_called()

    async def test_usage_is_recorded_as_a_task_without_restarting_the_keepalive(self):
        from open_webui.utils import usage as usage_utils

        call = MagicMock()
        call.reply_usage = {"organization_id": "o", "user_id": "u", "message_id": "a1"}
        call._replace.return_value = "REPLACED"
        send = AsyncMock(return_value={"usage": {}})
        bind = AsyncMock(side_effect=lambda response, context: response)
        with patch.object(usage_utils, "check_usage_caps"), patch.object(
            openai_router, "_send_provider_call", new=send
        ), patch.object(openai_router, "bind_usage_to_response", new=bind):
            await openai_router.send_after_call(call, MagicMock(), "P", "task")
        self.assertEqual(call._replace.call_args.kwargs, {"payload": "P", "reply_usage": None})
        self.assertEqual(send.await_args.args[0], "REPLACED")
        self.assertEqual(bind.await_args.args[1]["source"], "task")
