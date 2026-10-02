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
        import contextvars
        import threading

        client = MagicMock()
        trace = MagicMock(trace_id="a" * 32, id="b" * 16)
        client.start_observation.return_value = trace
        mock_get_client.return_value = client
        calls = []
        update_started = threading.Event()
        release_update = threading.Event()
        end_joining = threading.Event()

        def _update(**kwargs):
            update_started.set()
            release_update.wait(timeout=5)
            calls.append("update")

        trace.update.side_effect = _update
        trace.end.side_effect = lambda: calls.append("end")

        with patch("langfuse.propagate_attributes", create=True):
            lf.begin_chat_trace(
                user=MagicMock(email="bob@example.com", id="uid-99"),
                metadata={"chat_id": "chat-1"},
                form_data={"model": "m", "messages": []},
            )
        input_thread = lf._input_thread_var.get()
        self.assertTrue(update_started.wait(timeout=5))

        class _JoinSignal:
            def join(self, timeout=None):
                end_joining.set()
                input_thread.join(timeout)

            def is_alive(self):
                return input_thread.is_alive()

        lf._input_thread_var.set(_JoinSignal())
        ctx = contextvars.copy_context()
        ender = threading.Thread(target=ctx.run, args=(lf.end_chat_trace,))
        ender.start()
        self.assertTrue(end_joining.wait(timeout=5))
        trace.end.assert_not_called()
        release_update.set()
        ender.join(timeout=5)
        input_thread.join(timeout=5)
        self.assertFalse(ender.is_alive())
        self.assertEqual(calls, ["update", "end"])
        self.assertIsNone(ctx.run(lf.current_trace))

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


class BeginChatTraceNeverRaisesTest(unittest.TestCase):
    def setUp(self):
        _reset_trace_state()

    def tearDown(self):
        _reset_trace_state()

    def _begin(self):
        return lf.begin_chat_trace(
            user=MagicMock(email="bob@example.com", id="uid-99"),
            metadata={"chat_id": "chat-1"},
            form_data={"model": "m", "messages": [{"role": "user", "content": "hi"}]},
        )

    def _assert_no_trace(self, result, threads_before):
        import threading

        self.assertIsNone(result)
        self.assertIsNone(lf._trace_var.get())
        self.assertIsNone(lf._input_thread_var.get())
        self.assertIsNone(lf._propagate_cm_var.get())
        names = {t.name for t in threading.enumerate()} - threads_before
        self.assertNotIn("langfuse-chat-trace-input", names)

    def _threads(self):
        import threading

        return {t.name for t in threading.enumerate()}

    @patch.object(lf, "tracing_enabled", return_value=True)
    def test_create_chat_trace_raises(self, _enabled):
        before = self._threads()
        with patch.object(lf, "_create_chat_trace", side_effect=RuntimeError("boom")):
            result = self._begin()
        self._assert_no_trace(result, before)

    @patch.object(lf, "tracing_enabled", return_value=True)
    def test_get_client_raises(self, _enabled):
        before = self._threads()
        with patch.object(lf, "get_client", side_effect=RuntimeError("boom")):
            result = self._begin()
        self._assert_no_trace(result, before)

    @patch.object(lf, "tracing_enabled", return_value=True)
    @patch.object(lf, "get_client")
    def test_deepcopy_raises(self, mock_get_client, _enabled):
        client = MagicMock()
        mock_get_client.return_value = client
        before = self._threads()
        with patch.object(lf.copy, "deepcopy", side_effect=RuntimeError("boom")):
            result = self._begin()
        self._assert_no_trace(result, before)
        client.start_observation.assert_not_called()

    @patch.object(lf, "tracing_enabled", return_value=True)
    @patch.object(lf, "get_client")
    @patch("langfuse.propagate_attributes", create=True)
    def test_no_root_span_exits_entered_cm(
        self, mock_propagate, mock_get_client, _enabled
    ):
        client = MagicMock()
        client.start_observation.return_value = None
        mock_get_client.return_value = client
        cm = MagicMock()
        mock_propagate.return_value = cm
        before = self._threads()
        result = self._begin()
        self._assert_no_trace(result, before)
        cm.__enter__.assert_called_once()
        cm.__exit__.assert_called_once_with(None, None, None)

    @patch.object(lf, "tracing_enabled", return_value=True)
    @patch.object(lf, "get_client")
    @patch("langfuse.propagate_attributes", create=True)
    def test_thread_failure_ends_root_span_and_exits_cm(
        self, mock_propagate, mock_get_client, _enabled
    ):
        client = MagicMock()
        trace = MagicMock(trace_id="a" * 32, id="b" * 16)
        client.start_observation.return_value = trace
        mock_get_client.return_value = client
        cm = MagicMock()
        mock_propagate.return_value = cm
        before = self._threads()
        with patch.object(lf.threading, "Thread", side_effect=RuntimeError("boom")):
            result = self._begin()
        self._assert_no_trace(result, before)
        client.start_observation.assert_called_once()
        trace.end.assert_called_once()
        cm.__exit__.assert_called_once_with(None, None, None)

    @patch.object(lf, "tracing_enabled", return_value=True)
    @patch.object(lf, "get_client")
    @patch("langfuse.propagate_attributes", create=True)
    def test_cm_enter_failure_still_traces_without_propagation(
        self, mock_propagate, mock_get_client, _enabled
    ):
        client = MagicMock()
        trace = MagicMock(trace_id="a" * 32, id="b" * 16)
        client.start_observation.return_value = trace
        mock_get_client.return_value = client
        cm = MagicMock()
        cm.__enter__.side_effect = RuntimeError("boom")
        mock_propagate.return_value = cm
        result = self._begin()
        self.assertIs(result, trace)
        client.start_observation.assert_called_once()
        self.assertIsNone(lf._propagate_cm_var.get())
        lf.end_chat_trace()
        trace.end.assert_called_once()
        self.assertIsNone(lf.current_trace())
        cm.__exit__.assert_not_called()


class EndChatTraceInputTimeoutTest(unittest.TestCase):
    def setUp(self):
        _reset_trace_state()

    def tearDown(self):
        _reset_trace_state()

    @patch.object(lf, "get_client", return_value=None)
    def test_logs_when_input_not_attached(self, _client):
        stuck = MagicMock()
        stuck.is_alive.return_value = True
        lf._input_thread_var.set(stuck)
        trace = MagicMock()
        lf._trace_var.set(trace)
        with self.assertLogs(lf.log, level="DEBUG") as logs:
            lf.end_chat_trace()
        stuck.join.assert_called_once_with(timeout=5.0)
        self.assertTrue(any("not attached" in line for line in logs.output))
        trace.end.assert_called_once()


class OpenRouterTraceIdPairTest(unittest.TestCase):
    def _trace_object(self, trace):
        return lf._openrouter_trace_fields(
            trace=trace,
            trace_metadata={"chat_id": "chat-1"},
            user=MagicMock(email="bob@example.com", id="uid-99"),
            metadata=None,
        )["trace"]

    def test_both_ids_present(self):
        out = self._trace_object(MagicMock(trace_id="a" * 32, id="b" * 16))
        self.assertEqual(out["trace_id"], "a" * 32)
        self.assertEqual(out["parent_span_id"], "b" * 16)

    def test_missing_span_id_drops_both(self):
        out = self._trace_object(MagicMock(trace_id="a" * 32, id=None))
        self.assertNotIn("trace_id", out)
        self.assertNotIn("parent_span_id", out)
        self.assertEqual(out["generation_name"], "llm")

    def test_missing_trace_id_drops_both(self):
        out = self._trace_object(MagicMock(trace_id=None, id="b" * 16))
        self.assertNotIn("trace_id", out)
        self.assertNotIn("parent_span_id", out)


class MetadataStyleNoWarnTest(unittest.TestCase):
    def setUp(self):
        lf._warned_tracing_styles.clear()

    def tearDown(self):
        lf._warned_tracing_styles.clear()

    def test_unknown_metadata_style_is_app_without_logging(self):
        with patch.object(lf.log, "warning") as warning:
            style = lf.model_call_tracing_style(
                {"model_call_tracing": "client-chosen"}, warn_unknown=False
            )
        self.assertEqual(style, "app")
        warning.assert_not_called()
        self.assertEqual(lf._warned_tracing_styles, set())

    def test_known_metadata_style_passes(self):
        self.assertEqual(
            lf.model_call_tracing_style(
                {"model_call_tracing": "openrouter"}, warn_unknown=False
            ),
            "openrouter",
        )


class ProviderCallErrorSpanTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        _reset_trace_state()
        self.trace = MagicMock()
        self.span = MagicMock()
        self.trace.start_observation.return_value = self.span
        lf._trace_var.set(self.trace)

    async def asyncTearDown(self):
        _reset_trace_state()

    def _assert_error_span(self, message_part):
        kwargs = self.trace.start_observation.call_args.kwargs
        self.assertEqual(kwargs["name"], "llm")
        self.assertEqual(kwargs["as_type"], "span")
        self.assertEqual(kwargs["level"], "ERROR")
        self.assertIn(message_part, kwargs["status_message"])
        self.assertEqual(kwargs["metadata"], {"model_call_tracing": "openrouter"})
        for key in ("usage_details", "cost_details", "model"):
            self.assertNotIn(key, kwargs)
        self.span.end.assert_called_once()

    async def test_raised_error_records_span_and_reraises(self):
        from fastapi import HTTPException

        async def coro():
            raise HTTPException(status_code=502, detail="upstream timeout")

        with self.assertRaises(HTTPException):
            await lf.observe_generation({"model": "m"}, coro(), style="openrouter")
        self._assert_error_span("HTTP 502: upstream timeout")

    async def test_error_status_stream_records_span(self):
        from starlette.responses import StreamingResponse

        async def body():
            yield b"data: {}\n\n"

        async def coro():
            return StreamingResponse(body(), status_code=429)

        response = await lf.observe_generation(
            {"model": "m"}, coro(), style="openrouter"
        )
        self.assertEqual(response.status_code, 429)
        self._assert_error_span("HTTP 429")

    async def test_success_records_nothing(self):
        async def coro():
            return {"choices": [{"message": {"content": "ok"}}]}

        await lf.observe_generation({"model": "m"}, coro(), style="openrouter")
        self.trace.start_observation.assert_not_called()


if __name__ == "__main__":
    unittest.main()
