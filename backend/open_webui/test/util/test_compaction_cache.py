"""Compaction re-sends the reply's last call, still cached, kept by the keep-alive."""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from open_webui.routers import openai as openai_router
from open_webui.utils import cache_keepalive


def _call(message_id="a1"):
    payload = {
        "model": "anthropic/claude-opus-5.5",
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_completion_tokens": 64000,
        "messages": [{"role": "system", "content": "SYSTEM"}, {"role": "user", "content": "plot rain"}],
        "tools": [{"type": "function", "function": {"name": "run"}}],
        "trace": {"generation_name": "chat"},
    }
    call = MagicMock(
        payload=json.dumps(payload),
        reply_usage={"message_id": message_id, "organization_id": "o", "user_id": "u"},
        chat_id="c",
    )
    call._replace.side_effect = lambda **kw: kw
    return call


class ResentPayloadTest(unittest.TestCase):
    def test_the_request_is_kept_and_the_messages_added_after_it(self):
        extra = [{"role": "assistant", "content": "done"}, {"role": "user", "content": "summarize"}]
        body = json.loads(openai_router.resent_payload(_call(), 16000, "chat-compaction", extra))
        self.assertEqual(body["messages"][:2], json.loads(_call().payload)["messages"])
        self.assertEqual(body["messages"][2:], extra)
        self.assertEqual(body["tools"][0]["function"]["name"], "run")
        self.assertIs(body["stream"], False)
        self.assertEqual(body["max_tokens"], 16000)
        self.assertNotIn("stream_options", body)
        self.assertNotIn("max_completion_tokens", body)
        self.assertEqual(body["trace"]["generation_name"], "chat-compaction")

    def test_the_keepalive_adds_nothing(self):
        body = json.loads(openai_router.resent_payload(_call(), 1, "cache-keepalive"))
        self.assertEqual(len(body["messages"]), 2)
        self.assertEqual(body["max_tokens"], 1)


class ResendLastCallTest(unittest.IsolatedAsyncioTestCase):
    async def _resend(self, warm, user_id="u", message_id="a1", caps=None):
        from open_webui.utils import usage as usage_utils

        send = AsyncMock(return_value={"choices": []})
        bind = AsyncMock(side_effect=lambda response, context: response)
        with patch.object(cache_keepalive, "warm_call", return_value=warm), patch.object(
            usage_utils, "check_usage_caps", side_effect=caps
        ), patch.object(openai_router, "_send_provider_call", new=send), patch.object(
            openai_router, "bind_usage_to_response", new=bind
        ):
            result = await openai_router.resend_last_call(
                "c", MagicMock(id=user_id), message_id, [{"role": "user", "content": "x"}], 100
            )
        return result, send, bind

    async def test_the_warm_call_is_sent_on_its_connection_and_recorded_as_a_task(self):
        result, send, bind = await self._resend((_call(), MagicMock(id="u")))
        sent = send.await_args.args[0]
        self.assertIsNone(sent["reply_usage"])
        self.assertEqual(json.loads(sent["payload"])["messages"][-1]["content"], "x")
        self.assertEqual(result[1], len(sent["payload"]))
        self.assertEqual(bind.await_args.args[1]["source"], "task")

    async def test_no_warm_call_another_user_or_another_reply_sends_nothing(self):
        for warm, user_id, message_id in (
            (None, "u", "a1"),
            ((_call(), MagicMock(id="someone-else")), "u", "a1"),
            ((_call("a2"), MagicMock(id="u")), "u", "a1"),
        ):
            result, send, _ = await self._resend(warm, user_id, message_id)
            self.assertIsNone(result)
            send.assert_not_called()

    async def test_a_spending_limit_stops_it(self):
        with self.assertRaises(RuntimeError):
            await self._resend((_call(), MagicMock(id="u")), caps=RuntimeError("limit"))


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
