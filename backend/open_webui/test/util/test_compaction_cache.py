"""Compaction's summary call reads the chat's prompt cache when that is cheaper."""

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


class CachedPlanTest(unittest.TestCase):
    def test_a_large_conversation_reuses_the_last_request(self):
        plan = cc._cached_plan(CHAIN, "a1", (_call(), None), None, None, 100_000, 4_000_000)
        body = json.loads(plan.payload)
        self.assertEqual(body["messages"][1], {"role": "user", "content": "plot rain"})
        self.assertEqual(body["messages"][2], {"role": "assistant", "content": FINAL})
        self.assertEqual(body["messages"][3]["content"], cc.CACHED_INSTRUCTIONS)
        self.assertEqual(body["tools"][0]["function"]["name"], "run")
        self.assertIs(body["stream"], False)
        self.assertEqual(body["max_tokens"], cc.SUMMARY_MAX_TOKENS)
        self.assertNotIn("stream_options", body)
        self.assertTrue(0 < plan.removed_share < 1)

    def test_a_small_conversation_is_sent_fresh(self):
        # 0.05 x 160k = 8k cached tokens costs more than a 5k-token conversation.
        self.assertIsNone(
            cc._cached_plan(CHAIN, "a1", (_call(), None), None, None, 160_000, 20_000)
        )

    def test_the_price_follows_the_model(self):
        self.assertEqual(cc.cache_read_rate("anthropic/claude-fable-5.2"), 0.025)
        self.assertEqual(cc.cache_read_rate("requesty/anthropic/claude-opus-5-5"), 0.05)
        self.assertEqual(cc.cache_read_rate("anthropic/claude-opus-4-8"), 0.1)

    def test_another_reply_or_no_warm_cache_is_sent_fresh(self):
        self.assertIsNone(
            cc._cached_plan(CHAIN, "a1", (_call("other"), None), None, None, 1000, 4_000_000)
        )
        self.assertIsNone(cc._cached_plan(CHAIN, "a1", None, None, None, 1000, 4_000_000))

    def test_a_reply_that_ended_in_a_tool_call_is_sent_fresh(self):
        chain = [CHAIN[0], {"role": "assistant", "content": "", "tool_calls": [{"id": "t"}]}]
        self.assertIsNone(
            cc._cached_plan(chain, "a1", (_call(), None), None, None, 1000, 4_000_000)
        )

    def test_during_a_reply_the_turns_messages_are_extended(self):
        turn = [{"role": "system", "content": "SYSTEM"}, *CHAIN]
        plan = cc._cached_plan([], "a1", (_call("a2"), None), turn, [], 100_000, 4_000_000)
        self.assertIsNone(plan.payload)
        self.assertEqual(plan.messages[:3], turn)
        self.assertEqual(plan.messages[3]["content"], cc.CACHED_INSTRUCTIONS)


class SummarizeTest(unittest.IsolatedAsyncioTestCase):
    def _started(self, plan):
        usage = {"context_used": 900_000, "context_window": 1_000_000}
        return cc.Started([], usage, {}, "FRESH", plan)

    async def test_the_reused_request_is_sent_on_the_calls_connection(self):
        reply = {
            "choices": [{"message": {"content": "S"}}],
            "usage": {"prompt_tokens": 900_000, "completion_tokens": 2_000},
        }
        send = AsyncMock(return_value=reply)
        warm = (_call(), MagicMock())
        with patch.object(openai_router, "send_after_call", new=send), patch.object(
            cc, "_call_model", new=AsyncMock()
        ) as fresh:
            summary, estimate = await cc._summarize(
                MagicMock(), MagicMock(), "m", self._started(cc.CachedPlan("P", None, 0.8)), {}, warm, None
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
                MagicMock(), MagicMock(), "m", self._started(cc.CachedPlan("P", None, 0.8)), {}, (_call(), MagicMock()), None
            )
        self.assertEqual(summary, "S")
        self.assertEqual(fresh.await_args.args[3]["messages"][0]["content"], "FRESH")

    async def test_during_a_reply_the_call_marks_the_previous_turn(self):
        fresh = AsyncMock(return_value=("S", {"prompt_tokens": 10, "completion_tokens": 1}))
        messages = [*CHAIN, {"role": "user", "content": cc.CACHED_INSTRUCTIONS}]
        tools = [{"type": "function"}]
        with patch.object(cc, "_call_model", new=fresh):
            await cc._summarize(
                MagicMock(), MagicMock(), "m", self._started(cc.CachedPlan(None, messages, 0.5)), {"task": "t"}, None, tools
            )
        form = fresh.await_args.args[3]
        self.assertEqual(form["messages"], messages)
        self.assertEqual(form["tools"], tools)
        self.assertEqual(form["metadata"][openai_router.PREVIOUS_TURN_KEY], 2)


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


class PreviousTurnMarkerTest(unittest.TestCase):
    def test_position_counts_from_the_end_of_the_call(self):
        base = [{"role": "system"}, {"role": "user"}, {"role": "assistant"}, {"role": "user"}]
        key = openai_router.PREVIOUS_TURN_KEY
        self.assertEqual(cc.previous_turn_marker(base, base), {key: 2})
        call = [*base, {"role": "assistant"}, {"role": "tool"}]
        self.assertEqual(cc.previous_turn_marker(base, call), {key: 4})

    def test_a_first_turn_has_none(self):
        self.assertEqual(cc.previous_turn_marker([{"role": "user"}], [{"role": "user"}]), {})


class RouterMarkerTest(unittest.TestCase):
    def _cache(self, messages, from_end):
        payload = {"model": "anthropic/claude-opus-5-5", "messages": messages}
        return openai_router.enable_prompt_caching(
            "https://example.test", payload, {openai_router.PREVIOUS_TURN_KEY: from_end}
        )["messages"]

    def test_the_end_of_the_previous_turn_gets_a_marker(self):
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "now"},
        ]
        out = self._cache(messages, 2)
        self.assertEqual(out[2]["content"][0]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(out[2]["content"][0]["text"], "old answer")
        self.assertEqual(out[3]["content"], "now")
        self.assertEqual(messages[2]["content"], "old answer")

    def test_an_empty_tool_call_message_is_left_alone(self):
        messages = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t"}]},
            {"role": "user", "content": "now"},
        ]
        self.assertEqual(self._cache(messages, 2)[1]["content"], "")


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
