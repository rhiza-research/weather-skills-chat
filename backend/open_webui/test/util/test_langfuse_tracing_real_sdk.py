"""Tracing tests against the real Langfuse SDK.

The client is a real ``langfuse.Langfuse`` whose spans go to an in-memory
OpenTelemetry exporter through the SDK's ``span_exporter`` parameter, so the
assertions read the spans the SDK would send and nothing leaves the process.
"""

import json
import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from langfuse import Langfuse
from langfuse._client.attributes import LangfuseOtelSpanAttributes as A
from langfuse._client.resource_manager import LangfuseResourceManager
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from starlette.responses import StreamingResponse

from open_webui.utils import langfuse_tracing as lf

PUBLIC_KEY = "pk-lf-test"
SECRET_KEY = "sk-lf-test"
ENVIRONMENT = "harness-test"

USER = SimpleNamespace(email="bob@example.com", id="uid-99")
METADATA = {"chat_id": "chat-1", "message_id": "msg-1", "tool_ids": ["skills"]}
MESSAGES = [{"role": "user", "content": "rain in Nairobi?"}]
FORM_DATA = {"model": "weather-agent", "messages": MESSAGES}

# Each trace-metadata value as propagate_attributes records it: its str().
EXPECTED_TRACE_ATTRIBUTES = {
    A.TRACE_USER_ID: "bob@example.com",
    A.TRACE_SESSION_ID: "chat-1",
    A.TRACE_TAGS: ("weather-skills", "chat"),
    f"{A.TRACE_METADATA}.chat_id": "chat-1",
    f"{A.TRACE_METADATA}.message_id": "msg-1",
    f"{A.TRACE_METADATA}.model": "weather-agent",
    f"{A.TRACE_METADATA}.tool_ids": "['skills']",
    f"{A.TRACE_METADATA}.user_id": "uid-99",
    f"{A.TRACE_METADATA}.source": "chat",
    f"{A.TRACE_METADATA}.function_calling": "None",
}


def _hex_trace_id(span) -> str:
    return format(span.context.trace_id, "032x")


def _hex_span_id(span) -> str:
    return format(span.context.span_id, "016x")


def _drop_resource_manager():
    # The SDK keeps one resource manager per public key in this private dict
    # and hands it to every later client with that key, exporter included.
    # Removing the entry gives each test a client on its own exporter.
    LangfuseResourceManager._instances.pop(PUBLIC_KEY, None)


class RealLangfuseTestCase(unittest.IsolatedAsyncioTestCase):
    maxDiff = None

    def setUp(self):
        saved = {
            name: getattr(lf, name)
            for name in (
                "_client",
                "_client_failed",
                "LANGFUSE_ENABLED",
                "LANGFUSE_PUBLIC_KEY",
                "LANGFUSE_SECRET_KEY",
                "LANGFUSE_TRACING_ENVIRONMENT",
            )
        }
        self.addCleanup(self._restore_module, saved)
        self._reset_context()
        self.addCleanup(self._reset_context)
        _drop_resource_manager()
        self.addCleanup(_drop_resource_manager)

        self.exporter = InMemorySpanExporter()
        # A private provider keeps the process-wide OpenTelemetry provider unset.
        self.tracer_provider = TracerProvider()
        self.addCleanup(self.tracer_provider.shutdown)
        self.client = Langfuse(
            public_key=PUBLIC_KEY,
            secret_key=SECRET_KEY,
            environment=ENVIRONMENT,
            tracer_provider=self.tracer_provider,
            span_exporter=self.exporter,
        )
        self.addCleanup(self.client.shutdown)
        self.addCleanup(lf._exit_propagate_attributes)
        self.addCleanup(self._join_input_thread)

        lf.LANGFUSE_ENABLED = True
        lf.LANGFUSE_PUBLIC_KEY = PUBLIC_KEY
        lf.LANGFUSE_SECRET_KEY = SECRET_KEY
        lf.LANGFUSE_TRACING_ENVIRONMENT = ENVIRONMENT
        lf._client = self.client
        lf._client_failed = False

    @staticmethod
    def _restore_module(saved):
        for name, value in saved.items():
            setattr(lf, name, value)

    @staticmethod
    def _reset_context():
        lf._trace_var.set(None)
        lf._generation_stack_var.set(None)
        lf._propagate_cm_var.set(None)
        lf._trace_metadata_var.set(None)
        lf._input_thread_var.set(None)

    @staticmethod
    def _join_input_thread():
        thread = lf._input_thread_var.get()
        if thread is not None:
            thread.join(timeout=5)

    def _begin(self):
        return lf.begin_chat_trace(
            user=USER, metadata=dict(METADATA), form_data=FORM_DATA
        )

    def _end(self, **kwargs):
        thread = lf._input_thread_var.get()
        lf.end_chat_trace(**kwargs)
        if thread is not None:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.client.flush()

    def _spans(self):
        return self.exporter.get_finished_spans()

    def _root(self):
        roots = [s for s in self._spans() if s.name == "weather-skills-chat"]
        self.assertEqual(len(roots), 1, [s.name for s in self._spans()])
        return roots[0]

    def _children(self, root):
        return [
            s
            for s in self._spans()
            if s.parent is not None and s.parent.span_id == root.context.span_id
        ]

    def _of_type(self, observation_type):
        return [
            s
            for s in self._spans()
            if s.attributes.get(A.OBSERVATION_TYPE) == observation_type
        ]


class RootSpanTest(RealLangfuseTestCase):
    def test_root_ids_exist_now_and_root_exports_with_messages(self):
        trace = self._begin()

        self.assertIsNotNone(trace)
        self.assertRegex(trace.trace_id, r"^[0-9a-f]{32}$")
        self.assertRegex(trace.id, r"^[0-9a-f]{16}$")
        self.assertEqual(self._spans(), ())

        self._end(output={"content": "light rain"})

        root = self._root()
        self.assertIsNone(root.parent)
        self.assertEqual(_hex_trace_id(root), trace.trace_id)
        self.assertEqual(_hex_span_id(root), trace.id)
        self.assertEqual(root.attributes[A.OBSERVATION_TYPE], "span")
        self.assertEqual(root.attributes[A.ENVIRONMENT], ENVIRONMENT)
        self.assertEqual(
            json.loads(root.attributes[A.OBSERVATION_INPUT]),
            {
                "model": "weather-agent",
                "messages": [{"role": "user", "content": "rain in Nairobi?"}],
            },
        )
        self.assertEqual(
            json.loads(root.attributes[A.OBSERVATION_OUTPUT]),
            {"content": "light rain"},
        )


class PropagatedAttributesTest(RealLangfuseTestCase):
    async def test_root_and_child_spans_carry_trace_attributes(self):
        trace = self._begin()
        tool = lf.start_tool_observation("ecmwf_fetch", {"bbox": "1,2,3,4"})
        lf.end_tool_observation(tool, output={"ok": True})

        async def call():
            return {"choices": [{"message": {"content": "ok"}}]}

        await lf.observe_generation(
            {"model": "openai/gpt-4o", "messages": MESSAGES}, call(), style="app"
        )
        self._end()

        root = self._root()
        children = self._children(root)
        self.assertEqual(len(children), 2, [s.name for s in children])
        spans = (root, *children)
        for span in spans:
            self.assertEqual(_hex_trace_id(span), trace.trace_id)
        keys = EXPECTED_TRACE_ATTRIBUTES
        self.assertEqual(
            {s.name: {k: s.attributes.get(k) for k in keys} for s in spans},
            {s.name: EXPECTED_TRACE_ATTRIBUTES for s in spans},
        )

    def test_span_after_end_carries_no_trace_attributes(self):
        self._begin()
        self._end()
        self.exporter.clear()

        self.client.start_observation(name="after-chat", as_type="span").end()
        self.client.flush()

        (after,) = self._spans()
        self.assertEqual(after.name, "after-chat")
        self.assertNotIn(A.TRACE_USER_ID, after.attributes)
        self.assertNotIn(A.TRACE_SESSION_ID, after.attributes)
        self.assertEqual(
            [k for k in after.attributes if k.startswith(A.TRACE_METADATA)], []
        )


class OpenRouterFieldsTest(RealLangfuseTestCase):
    def test_trace_fields_point_at_the_exported_root(self):
        self._begin()
        body = {"model": "openai/gpt-4o", "messages": MESSAGES, "stream": True}

        out = lf.apply_provider_trace_fields(
            body, "openrouter", user=USER, metadata=dict(METADATA)
        )
        self._end()

        root = self._root()
        self.assertEqual(out["trace"]["trace_id"], _hex_trace_id(root))
        self.assertEqual(out["trace"]["parent_span_id"], _hex_span_id(root))
        self.assertEqual(out["trace"]["environment"], ENVIRONMENT)
        self.assertEqual(root.attributes[A.ENVIRONMENT], ENVIRONMENT)
        self.assertEqual(out["user"], "bob@example.com")
        self.assertEqual(out["session_id"], "chat-1")


class TracingDisabledTest(RealLangfuseTestCase):
    async def test_disabled_exports_nothing(self):
        lf.LANGFUSE_ENABLED = False
        self.assertFalse(lf.tracing_enabled())

        self.assertIsNone(self._begin())

        async def call():
            return {"choices": [{"message": {"content": "ok"}}]}

        await lf.observe_generation(
            {"model": "openai/gpt-4o", "messages": MESSAGES}, call(), style="app"
        )
        self._end()

        self.assertEqual(self._spans(), ())


class AppGenerationTest(RealLangfuseTestCase):
    def _assert_one_generation(self, usage):
        root = self._root()
        generations = self._of_type("generation")
        self.assertEqual(len(generations), 1)
        generation = generations[0]
        self.assertEqual(generation.name, "llm")
        self.assertEqual(generation.parent.span_id, root.context.span_id)
        self.assertEqual(generation.context.trace_id, root.context.trace_id)
        self.assertEqual(
            generation.attributes[A.OBSERVATION_MODEL], "openai/gpt-4o"
        )
        self.assertEqual(
            json.loads(generation.attributes[A.OBSERVATION_USAGE_DETAILS]), usage
        )
        return generation

    async def test_one_generation_under_root(self):
        self._begin()

        async def call():
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                },
            }

        await lf.observe_generation(
            {"model": "openai/gpt-4o", "messages": MESSAGES}, call(), style="app"
        )
        self._end()

        self._assert_one_generation({"input": 1, "output": 2, "total": 3})

    async def test_streamed_generation_under_root(self):
        self._begin()

        async def body():
            yield b'data: {"choices":[{"delta":{"content":"light "}}]}\n\n'
            yield b'data: {"choices":[{"delta":{"content":"rain"}}]}\n\n'
            yield (
                b'data: {"usage":{"prompt_tokens":4,"completion_tokens":5,'
                b'"total_tokens":9}}\n\n'
            )
            yield b"data: [DONE]\n\n"

        async def call():
            return StreamingResponse(body(), media_type="text/event-stream")

        response = await lf.observe_generation(
            {"model": "openai/gpt-4o", "messages": MESSAGES}, call(), style="app"
        )
        self.assertEqual(self._of_type("generation"), [])
        chunks = [chunk async for chunk in response.body_iterator]
        self.assertEqual(len(chunks), 4)
        self._end()

        generation = self._assert_one_generation(
            {"input": 4, "output": 5, "total": 9}
        )
        self.assertEqual(
            json.loads(generation.attributes[A.OBSERVATION_OUTPUT]),
            {"content": "light rain"},
        )


class OpenRouterGenerationTest(RealLangfuseTestCase):
    async def test_success_exports_no_generation(self):
        self._begin()

        async def call():
            return {"choices": [{"message": {"content": "ok"}}]}

        await lf.observe_generation(
            {"model": "openai/gpt-4o", "messages": MESSAGES},
            call(),
            style="openrouter",
        )
        self._end()

        root = self._root()
        self.assertEqual(self._of_type("generation"), [])
        self.assertEqual(self._children(root), [])

    async def test_failure_exports_error_span_and_reraises(self):
        self._begin()

        async def call():
            raise HTTPException(status_code=502, detail="upstream timeout")

        with self.assertRaises(HTTPException):
            await lf.observe_generation(
                {"model": "openai/gpt-4o", "messages": MESSAGES},
                call(),
                style="openrouter",
            )
        self._end()

        root = self._root()
        self.assertEqual(self._of_type("generation"), [])
        children = self._children(root)
        self.assertEqual(len(children), 1, [s.name for s in children])
        span = children[0]
        self.assertEqual(span.name, "llm")
        self.assertEqual(span.attributes[A.OBSERVATION_TYPE], "span")
        self.assertEqual(span.attributes[A.OBSERVATION_LEVEL], "ERROR")
        self.assertEqual(
            span.attributes[A.OBSERVATION_STATUS_MESSAGE],
            "HTTP 502: upstream timeout",
        )
        for key in (
            A.OBSERVATION_USAGE_DETAILS,
            A.OBSERVATION_COST_DETAILS,
            A.OBSERVATION_MODEL,
        ):
            self.assertNotIn(key, span.attributes)


if __name__ == "__main__":
    unittest.main()
