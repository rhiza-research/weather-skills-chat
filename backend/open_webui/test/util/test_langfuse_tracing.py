"""Unit tests for Langfuse tracing helpers."""

from __future__ import annotations

import asyncio
import json
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
        lf._trace_metadata_var.set(None)
        lf._input_thread_var.set(None)

    @patch.object(lf, "tracing_enabled", return_value=True)
    @patch.object(lf, "get_client")
    @patch("langfuse.propagate_attributes", create=True)
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


def _reset_trace_state():
    lf._client = None
    lf._client_failed = False
    lf._trace_var.set(None)
    lf._generation_stack_var.set(None)
    lf._propagate_cm_var.set(None)
    lf._trace_metadata_var.set(None)
    lf._input_thread_var.set(None)


class BeginChatTraceTest(unittest.TestCase):
    def setUp(self):
        _reset_trace_state()

    def tearDown(self):
        thread = lf._input_thread_var.get()
        if thread is not None:
            thread.join(timeout=1)
        _reset_trace_state()

    @patch.object(lf, "tracing_enabled", return_value=True)
    @patch.object(lf, "get_client")
    @patch("langfuse.propagate_attributes", create=True)
    def test_root_ids_ready_now_and_input_attached_later(
        self, mock_propagate, mock_get_client, _enabled
    ):
        import threading

        client = MagicMock()
        trace = MagicMock(trace_id="a" * 32, id="b" * 16)
        client.start_observation.return_value = trace
        mock_get_client.return_value = client
        cm = MagicMock()
        mock_propagate.return_value = cm
        gate = threading.Event()
        trace.update.side_effect = lambda **kwargs: gate.wait(timeout=1)
        messages = [{"role": "user", "content": "rain in Nairobi?"}]

        returned = lf.begin_chat_trace(
            user=MagicMock(email="bob@example.com", id="uid-99"),
            metadata={"chat_id": "chat-1", "message_id": "msg-1"},
            form_data={"model": "weather-agent", "messages": messages},
        )

        self.assertIs(returned, trace)
        self.assertIs(lf.current_trace(), trace)
        self.assertEqual(lf.current_trace().trace_id, "a" * 32)
        self.assertEqual(lf.current_trace().id, "b" * 16)
        cm.__enter__.assert_called_once()
        self.assertEqual(
            client.start_observation.call_args.kwargs["input"],
            {"model": "weather-agent", "messages": None},
        )
        self.assertEqual(lf._trace_metadata_var.get()["chat_id"], "chat-1")

        # The full input is still pending while the send path continues.
        thread = lf._input_thread_var.get()
        self.assertTrue(thread.is_alive())
        messages.append({"role": "assistant", "content": "mutated later"})
        gate.set()
        thread.join(timeout=1)
        self.assertEqual(
            trace.update.call_args.kwargs["input"],
            {
                "model": "weather-agent",
                "messages": [{"role": "user", "content": "rain in Nairobi?"}],
            },
        )

    @patch.object(lf, "tracing_enabled", return_value=True)
    @patch.object(lf, "get_client")
    def test_end_waits_for_input_before_ending(self, mock_get_client, _enabled):
        import threading

        client = MagicMock()
        trace = MagicMock(trace_id="a" * 32, id="b" * 16)
        client.start_observation.return_value = trace
        mock_get_client.return_value = client
        calls = []
        gate = threading.Event()

        def _update(**kwargs):
            gate.wait(timeout=1)
            calls.append("update")

        trace.update.side_effect = _update
        trace.end.side_effect = lambda: calls.append("end")

        with patch("langfuse.propagate_attributes", create=True):
            lf.begin_chat_trace(
                user=MagicMock(email="bob@example.com", id="uid-99"),
                metadata={"chat_id": "chat-1"},
                form_data={"model": "m", "messages": []},
            )
        threading.Timer(0.05, gate.set).start()
        lf.end_chat_trace()
        self.assertEqual(calls, ["update", "end"])
        self.assertIsNone(lf.current_trace())

    @patch.object(lf, "tracing_enabled", return_value=False)
    def test_disabled_creates_nothing(self, _enabled):
        self.assertIsNone(
            lf.begin_chat_trace(
                user=MagicMock(), metadata={}, form_data={"model": "m"}
            )
        )
        self.assertIsNone(lf.current_trace())


class ModelCallTracingStyleTest(unittest.TestCase):
    def setUp(self):
        lf._warned_tracing_styles.clear()

    def test_unset_is_app(self):
        self.assertEqual(lf.model_call_tracing_style({}), "app")
        self.assertEqual(lf.model_call_tracing_style(None), "app")
        self.assertEqual(lf.model_call_tracing_style({"enable": True}), "app")

    def test_openrouter(self):
        self.assertEqual(
            lf.model_call_tracing_style({"model_call_tracing": "openrouter"}),
            "openrouter",
        )

    def test_unknown_is_app_and_warns_once(self):
        with self.assertLogs(lf.log, level="WARNING") as logs:
            self.assertEqual(
                lf.model_call_tracing_style({"model_call_tracing": "litellm"}), "app"
            )
            self.assertEqual(
                lf.model_call_tracing_style({"model_call_tracing": "litellm"}), "app"
            )
        self.assertEqual(len(logs.records), 1)
        self.assertIn("litellm", logs.output[0])


class ApplyProviderTraceFieldsTest(unittest.TestCase):
    def setUp(self):
        _reset_trace_state()
        self.user = MagicMock(email="bob@example.com", id="uid-99")
        self.metadata = {"chat_id": "chat-1", "message_id": "msg-1"}

    def tearDown(self):
        _reset_trace_state()

    def _body(self):
        return {
            "model": "openai/gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": True,
        }

    @patch.object(lf, "tracing_enabled", return_value=True)
    def test_app_style_body_is_byte_identical(self, _enabled):
        lf._trace_var.set(MagicMock(trace_id="a" * 32, id="b" * 16))
        before = json.dumps(self._body())
        out = lf.apply_provider_trace_fields(
            self._body(), "app", user=self.user, metadata=self.metadata
        )
        self.assertEqual(json.dumps(out), before)

    @patch.object(lf, "tracing_enabled", return_value=True)
    def test_openrouter_with_trace(self, _enabled):
        lf._trace_var.set(MagicMock(trace_id="a" * 32, id="b" * 16))
        lf._trace_metadata_var.set(
            {
                "chat_id": "chat-1",
                "message_id": "msg-1",
                "model": "weather-agent",
                "tool_ids": ["skills"],
                "user_id": "uid-99",
            }
        )
        out = lf.apply_provider_trace_fields(
            self._body(), "openrouter", user=self.user, metadata=self.metadata
        )
        self.assertEqual(out["user"], "bob@example.com")
        self.assertEqual(out["session_id"], "chat-1")
        self.assertEqual(
            out["trace"],
            {
                "trace_id": "a" * 32,
                "parent_span_id": "b" * 16,
                "environment": lf.LANGFUSE_TRACING_ENVIRONMENT,
                "generation_name": "llm",
                "chat_id": "chat-1",
                "message_id": "msg-1",
                "model": "weather-agent",
                "tool_ids": ["skills"],
            },
        )
        self.assertEqual(out["messages"], self._body()["messages"])

    @patch.object(lf, "tracing_enabled", return_value=False)
    def test_openrouter_tracing_disabled_body_unchanged(self, _enabled):
        before = json.dumps(self._body())
        out = lf.apply_provider_trace_fields(
            self._body(), "openrouter", user=self.user, metadata=self.metadata
        )
        self.assertEqual(json.dumps(out), before)

    @patch.object(lf, "tracing_enabled", return_value=True)
    def test_openrouter_without_trace(self, _enabled):
        out = lf.apply_provider_trace_fields(
            self._body(), "openrouter", user=self.user, metadata=self.metadata
        )
        self.assertEqual(out["user"], "bob@example.com")
        self.assertEqual(out["session_id"], "chat-1")
        self.assertNotIn("trace", out)

    @patch.object(lf, "tracing_enabled", return_value=True)
    def test_openrouter_without_trace_or_chat(self, _enabled):
        out = lf.apply_provider_trace_fields(
            self._body(), "openrouter", user=self.user, metadata=None
        )
        self.assertEqual(out["user"], "bob@example.com")
        self.assertNotIn("session_id", out)
        self.assertNotIn("trace", out)

    @patch.object(lf, "tracing_enabled", return_value=True)
    def test_unknown_style_body_unchanged(self, _enabled):
        before = json.dumps(self._body())
        style = lf.model_call_tracing_style({"model_call_tracing": "litellm"})
        out = lf.apply_provider_trace_fields(
            self._body(), style, user=self.user, metadata=self.metadata
        )
        self.assertEqual(json.dumps(out), before)


class ProviderTracedGenerationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        _reset_trace_state()

    async def asyncTearDown(self):
        _reset_trace_state()

    @patch.object(lf, "tracing_enabled", return_value=True)
    async def test_openrouter_style_creates_no_generation(self, _enabled):
        trace = MagicMock()
        lf._trace_var.set(trace)
        response = {"choices": [{"message": {"content": "ok"}}]}

        async def coro():
            return response

        result = await lf.observe_generation(
            {"model": "m", "messages": []}, coro(), style="openrouter"
        )
        self.assertIs(result, response)
        trace.start_observation.assert_not_called()

    @patch.object(lf, "tracing_enabled", return_value=True)
    async def test_openrouter_style_leaves_outer_generation_open(self, _enabled):
        outer = MagicMock()
        lf._generation_stack().append(outer)

        async def coro():
            return {"choices": [{"message": {"content": "ok"}}]}

        await lf.observe_generation(
            {"model": "m", "messages": []}, coro(), style="openrouter"
        )
        outer.end.assert_not_called()
        self.assertEqual(lf._generation_stack(), [outer])

    @patch.object(lf, "tracing_enabled", return_value=True)
    async def test_app_style_still_records(self, _enabled):
        trace = MagicMock()
        generation = MagicMock()
        trace.start_observation.return_value = generation
        lf._trace_var.set(trace)

        async def coro():
            return {"choices": [{"message": {"content": "ok"}}]}

        await lf.observe_generation(
            {"model": "m", "messages": []}, coro(), style="app"
        )
        self.assertEqual(
            trace.start_observation.call_args.kwargs["as_type"], "generation"
        )
        generation.end.assert_called_once()


if __name__ == "__main__":
    unittest.main()
