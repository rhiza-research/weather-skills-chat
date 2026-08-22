"""Unit tests for Langfuse tracing helpers."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from open_webui.utils import langfuse_tracing as lf


class TruncatePayloadTest(unittest.TestCase):
    def test_small_object_roundtrips(self):
        self.assertEqual(lf.truncate_payload({"a": 1}), {"a": 1})

    def test_large_payload_truncates(self):
        big = {"x": "y" * 50_000}
        out = lf.truncate_payload(big, limit=100)
        self.assertIsInstance(out, str)
        self.assertIn("truncated", out)


class MapUsageTest(unittest.TestCase):
    def test_openai_tokens(self):
        self.assertEqual(
            lf.map_usage({"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}),
            {"input": 10, "output": 5, "total": 15},
        )

    def test_openrouter_cache_details(self):
        self.assertEqual(
            lf.map_usage(
                {
                    "prompt_tokens": 1000,
                    "completion_tokens": 10,
                    "total_tokens": 1010,
                    "prompt_tokens_details": {
                        "cached_tokens": 900,
                        "cache_write_tokens": 100,
                    },
                }
            ),
            {
                "input": 1000,
                "output": 10,
                "total": 1010,
                "cache_read_input_tokens": 900,
                "cache_creation_input_tokens": 100,
            },
        )


class TraceUserIdTest(unittest.TestCase):
    def test_prefers_email(self):
        user = MagicMock(email="alice@example.com", id="uid-1")
        self.assertEqual(lf._trace_user_id(user), "alice@example.com")

    def test_falls_back_to_id(self):
        user = MagicMock(email=None, id="uid-1")
        self.assertEqual(lf._trace_user_id(user), "uid-1")


class SseStateTest(unittest.TestCase):
    def test_accumulates_content_and_tool_calls(self):
        state = lf.new_sse_state()
        chunk = (
            'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"ecmwf_fetch","arguments":"{}"}}]}}]}\n\n'
            'data: {"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}\n\n'
        )
        lf.ingest_sse_chunk(state, chunk)
        out = lf.output_from_sse_state(state)
        self.assertEqual(out["content"], "hi")
        self.assertEqual(out["tool_calls"][0]["function"]["name"], "ecmwf_fetch")
        self.assertEqual(state["usage"]["total_tokens"], 3)


class ObserveGenerationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        lf._client = None
        lf._client_failed = False
        lf._trace_var.set(None)
        lf._generation_stack_var.set(None)
        lf._propagate_cm_var.set(None)

    @patch.object(lf, "tracing_enabled", return_value=True)
    @patch.object(lf, "get_client")
    async def test_observe_generation_ends_span(self, mock_get_client, _enabled):
        trace = MagicMock()
        generation = MagicMock()
        trace.start_observation.return_value = generation
        mock_get_client.return_value = trace
        lf._trace_var.set(trace)

        async def coro():
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
            }

        result = await lf.observe_generation({"model": "m", "messages": []}, coro())
        self.assertEqual(result["choices"][0]["message"]["content"], "ok")
        generation.update.assert_called_once()
        generation.end.assert_called_once()
        self.assertIn(
            "usage_details",
            generation.update.call_args.kwargs,
        )


class ToolObservationTest(unittest.TestCase):
    def setUp(self):
        lf._trace_var.set(None)
        lf._generation_stack_var.set(None)

    @patch.object(lf, "current_trace")
    def test_tool_span_lifecycle(self, mock_current):
        trace = MagicMock()
        span = MagicMock()
        trace.start_observation.return_value = span
        mock_current.return_value = trace
        obs = lf.start_tool_observation("ecmwf_fetch", {"bbox": "1,2,3,4"})
        lf.end_tool_observation(obs, output={"ok": True})
        trace.start_observation.assert_called_once()
        self.assertEqual(trace.start_observation.call_args.kwargs["as_type"], "tool")
        span.update.assert_called_once()
        span.end.assert_called_once()


class StartChatTraceTest(unittest.TestCase):
    def setUp(self):
        lf._client = None
        lf._client_failed = False
        lf._trace_var.set(None)
        lf._propagate_cm_var.set(None)

    @patch.object(lf, "tracing_enabled", return_value=True)
    @patch.object(lf, "get_client")
    @patch("langfuse.propagate_attributes")
    def test_uses_email_as_user_id(self, mock_propagate, mock_get_client, _enabled):
        client = MagicMock()
        trace = MagicMock()
        client.start_observation.return_value = trace
        mock_get_client.return_value = client
        cm = MagicMock()
        mock_propagate.return_value = cm

        user = MagicMock(email="bob@example.com", id="uid-99")
        lf.start_chat_trace(
            user=user,
            metadata={"chat_id": "chat-1"},
            form_data={"model": "gpt-4", "messages": []},
        )

        mock_propagate.assert_called_once()
        self.assertEqual(mock_propagate.call_args.kwargs["user_id"], "bob@example.com")
        self.assertEqual(mock_propagate.call_args.kwargs["session_id"], "chat-1")
        cm.__enter__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
