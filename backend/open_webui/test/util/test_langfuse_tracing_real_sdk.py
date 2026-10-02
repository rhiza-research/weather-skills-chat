"""Tracing tests against the real Langfuse SDK.

The client is a real ``langfuse.Langfuse`` whose spans go to an in-memory
OpenTelemetry exporter through the SDK's ``span_exporter`` parameter, so the
assertions read the spans the SDK would send and nothing leaves the process.
"""

import asyncio
import contextlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from langfuse import Langfuse
from langfuse._client.attributes import LangfuseOtelSpanAttributes as A
from langfuse._client.resource_manager import LangfuseResourceManager
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from starlette.responses import StreamingResponse

from open_webui import tasks as task_registry
from open_webui.routers import openai as openai_router
from open_webui.utils import automation_runner
from open_webui.utils import chat
from open_webui.utils import langfuse_tracing as lf
from open_webui.utils import usage as usage_module

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
        lf._trace_state_var.set(None)
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


ARENA_USAGE = {"prompt_tokens": 7, "completion_tokens": 8, "total_tokens": 15}
ADMIN = SimpleNamespace(
    id="uid-99", email="bob@example.com", name="Bob", role="admin"
)


class _FakeProviderResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    async def json(self):
        return {
            "choices": [{"message": {"content": "Rain outlook"}}],
            "usage": ARENA_USAGE,
        }

    def raise_for_status(self):
        pass

    def close(self):
        pass


class _FakeProviderSession:
    def __init__(self, sent):
        self.sent = sent

    async def request(self, **kwargs):
        self.sent.append(json.loads(kwargs["data"]))
        return _FakeProviderResponse()

    async def close(self):
        pass


def _arena_request(style):
    config = SimpleNamespace(
        OPENAI_API_BASE_URLS=["https://openrouter.ai/api/v1"],
        OPENAI_API_KEYS=["key"],
        OPENAI_API_CONFIGS={"0": {"model_call_tracing": style}},
    )
    models = {
        "arena-model": {
            "id": "arena-model",
            "owned_by": "arena",
            "info": {"meta": {"model_ids": ["openai/gpt-4o"]}},
        },
        "openai/gpt-4o": {"id": "openai/gpt-4o", "owned_by": "openai"},
    }
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=config, MODELS=models)),
        state=SimpleNamespace(),
        headers={},
    )


class ArenaTest(RealLangfuseTestCase):
    """An arena call is recorded once: by the selected model's call."""

    def setUp(self):
        super().setUp()
        self.sent = []
        self.usage_store = MagicMock()
        for p in (
            patch.object(chat, "enforce_usage_caps"),
            patch.object(usage_module, "Usage", self.usage_store),
            patch.object(openai_router.Models, "get_model_by_id", return_value=None),
            patch.object(
                openai_router.aiohttp,
                "ClientSession",
                side_effect=lambda **kwargs: _FakeProviderSession(self.sent),
            ),
        ):
            p.start()
            self.addCleanup(p.stop)

    def _form(self, stream):
        return {
            "model": "arena-model",
            "messages": list(MESSAGES),
            "stream": stream,
            "metadata": {"chat_id": "chat-1", "message_id": "msg-1"},
        }

    def _assert_usage_recorded_once(self):
        self.assertEqual(self.usage_store.record_event.call_count, 1)
        kwargs = self.usage_store.record_event.call_args.kwargs
        self.assertEqual(kwargs["usage"], ARENA_USAGE)
        self.assertEqual(kwargs["model_id"], "openai/gpt-4o")

    def _selected_model_generation(self):
        root = self._root()
        generations = self._of_type("generation")
        self.assertEqual(
            [g.attributes[A.OBSERVATION_MODEL] for g in generations],
            ["openai/gpt-4o"],
        )
        generation = generations[0]
        self.assertEqual(generation.parent.span_id, root.context.span_id)
        self.assertEqual(
            json.loads(generation.attributes[A.OBSERVATION_INPUT]),
            {"messages": MESSAGES},
        )
        return generation

    def _assert_one_selected_model_generation(self, output):
        generation = self._selected_model_generation()
        self.assertEqual(
            json.loads(generation.attributes[A.OBSERVATION_USAGE_DETAILS]),
            {"input": 7, "output": 8, "total": 15},
        )
        self.assertEqual(
            json.loads(generation.attributes[A.OBSERVATION_OUTPUT]), output
        )

    async def test_app_inner_non_streaming_records_one_generation(self):
        self._begin()

        response = await chat.generate_chat_completion(
            _arena_request("app"), self._form(stream=False), ADMIN
        )
        self._end()

        self.assertEqual(response["selected_model_id"], "openai/gpt-4o")
        self.assertEqual(response["choices"][0]["message"]["content"], "Rain outlook")
        self._assert_one_selected_model_generation({"content": "Rain outlook"})
        self._assert_usage_recorded_once()

    async def test_app_inner_failure_records_one_error_generation(self):
        self._begin()
        error = RuntimeError("provider down")

        with patch.object(
            chat, "generate_openai_chat_completion", side_effect=error
        ):
            with self.assertRaises(RuntimeError) as raised:
                await chat.generate_chat_completion(
                    _arena_request("app"), self._form(stream=False), ADMIN
                )
        self._end()

        self.assertIs(raised.exception, error)
        generation = self._selected_model_generation()
        self.assertEqual(generation.attributes[A.OBSERVATION_LEVEL], "ERROR")
        self.assertEqual(
            generation.attributes[A.OBSERVATION_STATUS_MESSAGE], "provider down"
        )
        self.usage_store.record_event.assert_not_called()

    async def test_selection_failure_records_nothing(self):
        self._begin()
        request = _arena_request("app")
        # No model other than the arena itself, so selection has nothing to
        # choose from and fails before any model call.
        request.app.state.MODELS.pop("openai/gpt-4o")
        request.app.state.MODELS["arena-model"]["info"] = {"meta": {}}

        with self.assertRaises(IndexError):
            await chat.generate_chat_completion(
                request, self._form(stream=False), ADMIN
            )
        self._end()

        self._root()
        self.assertEqual(self._of_type("generation"), [])
        self.assertEqual(self.sent, [])
        self.usage_store.record_event.assert_not_called()

    async def test_app_inner_streaming_records_one_generation(self):
        self._begin()

        async def body():
            yield b'data: {"choices":[{"delta":{"content":"light rain"}}]}\n\n'
            yield (
                b'data: {"usage":{"prompt_tokens":7,"completion_tokens":8,'
                b'"total_tokens":15}}\n\n'
            )
            yield b"data: [DONE]\n\n"

        async def provider_call(**kwargs):
            return StreamingResponse(body(), media_type="text/event-stream")

        with patch.object(
            chat, "generate_openai_chat_completion", side_effect=provider_call
        ):
            response = await chat.generate_chat_completion(
                _arena_request("app"), self._form(stream=True), ADMIN
            )
            chunks = [chunk async for chunk in response.body_iterator]
        self._end()

        self.assertEqual(
            chunks,
            [
                'data: {"selected_model_id": "openai/gpt-4o"}\n\n',
                b'data: {"choices":[{"delta":{"content":"light rain"}}]}\n\n',
                b'data: {"usage":{"prompt_tokens":7,"completion_tokens":8,'
                b'"total_tokens":15}}\n\n',
                b"data: [DONE]\n\n",
            ],
        )
        self._assert_one_selected_model_generation({"content": "light rain"})
        self._assert_usage_recorded_once()

    async def test_openrouter_inner_records_no_app_generation(self):
        self._begin()

        response = await chat.generate_chat_completion(
            _arena_request("openrouter"), self._form(stream=False), ADMIN
        )
        self._end()

        self.assertEqual(response["selected_model_id"], "openai/gpt-4o")
        root = self._root()
        self.assertEqual(self._of_type("generation"), [])
        self.assertEqual(self._children(root), [])
        (body,) = self.sent
        self.assertEqual(body["model"], "openai/gpt-4o")
        self.assertEqual(body["trace"]["trace_id"], _hex_trace_id(root))
        self.assertEqual(body["trace"]["parent_span_id"], _hex_span_id(root))
        self.assertEqual(body["user"], "bob@example.com")
        self._assert_usage_recorded_once()

    async def test_tracing_disabled_records_nothing(self):
        with patch.object(lf, "LANGFUSE_ENABLED", False):
            self.assertIsNone(self._begin())
            response = await chat.generate_chat_completion(
                _arena_request("openrouter"), self._form(stream=False), ADMIN
            )
            self._end()

        self.assertEqual(response["selected_model_id"], "openai/gpt-4o")
        self.assertEqual(self._spans(), ())
        for key in ("trace", "user"):
            self.assertNotIn(key, self.sent[0])
        self._assert_usage_recorded_once()


class AutomationTraceTest(RealLangfuseTestCase):
    """An automation run is one trace whose root ends after its tool loop.

    The middleware and model-call functions the runner calls are replaced by
    fakes that make the same tracing calls: the model call goes through
    observe_generation, and the tool loop task records a tool span and a
    generation, then ends the root span with the reply or "cancelled".
    """

    def setUp(self):
        super().setUp()
        self.chats = MagicMock()
        self.loop_started = asyncio.Event()
        self.loop_body = self._loop_success
        self.handler_error = None
        for p in (
            patch.object(automation_runner, "Chats", self.chats),
            patch.object(
                automation_runner, "process_chat_payload", self._process_payload
            ),
            patch.object(
                automation_runner, "chat_completion_handler", self._handler
            ),
            patch.object(
                automation_runner, "process_chat_response", self._process_response
            ),
        ):
            p.start()
            self.addCleanup(p.stop)

    async def _process_payload(self, request, form_data, user, metadata, model):
        return form_data, metadata, []

    async def _handler(self, request, form_data, user):
        async def call():
            if self.handler_error is not None:
                raise self.handler_error
            return {
                "choices": [{"message": {"content": "", "tool_calls": []}}],
                "usage": ARENA_USAGE,
            }

        return await lf.observe_generation(
            {"model": "openai/gpt-4o", "messages": form_data["messages"]},
            call(),
            style="app",
        )

    async def _process_response(
        self, request, response, form_data, user, metadata, model, events, tasks
    ):
        task_id, _ = task_registry.create_task(
            self.loop_body(), id=metadata["chat_id"]
        )
        return {"status": True, "task_id": task_id}

    async def _second_model_call(self):
        async def call():
            return {"choices": [{"message": {"content": "light rain"}}]}

        await lf.observe_generation(
            {"model": "openai/gpt-4o", "messages": MESSAGES}, call(), style="app"
        )

    async def _loop_success(self):
        tool = lf.start_tool_observation("ecmwf_fetch", {"bbox": "1,2,3,4"})
        lf.end_tool_observation(tool, output={"ok": True})
        await self._second_model_call()
        lf.end_chat_trace(output={"done": True, "content": "light rain"})

    async def _run(self):
        await automation_runner._stream_automation_chat(
            SimpleNamespace(state=SimpleNamespace()),
            run_id="run-1",
            chat_id="chat-auto",
            assistant_id="msg-auto",
            user=USER,
            model={"id": "weather-agent"},
            model_id="weather-agent",
            prompt="rain in Nairobi?",
            tool_ids=["skills"],
            features={},
            organization_id="org-1",
        )

    def _flush(self):
        self._join_input_thread()
        self.client.flush()

    def _assert_error_root(self, message):
        root = self._root()
        self.assertEqual(root.attributes[A.OBSERVATION_LEVEL], "ERROR")
        self.assertEqual(root.attributes[A.OBSERVATION_STATUS_MESSAGE], message)
        return root

    @contextlib.contextmanager
    def _no_otel_complaints(self):
        """No span ended twice and no context detached in the wrong task."""
        with self.assertNoLogs("opentelemetry.sdk.trace", level="WARNING"):
            with self.assertNoLogs("opentelemetry.context", level="ERROR"):
                yield

    async def test_success_is_one_trace_ended_after_the_tool_loop(self):
        with self._no_otel_complaints():
            await self._run()
        self._flush()

        root = self._root()
        self.assertEqual(root.attributes[A.TRACE_TAGS], ("weather-skills", "automation"))
        self.assertEqual(root.attributes[f"{A.TRACE_METADATA}.source"], "automation")
        self.assertEqual(root.attributes[A.TRACE_SESSION_ID], "chat-auto")
        self.assertEqual(
            json.loads(root.attributes[A.OBSERVATION_OUTPUT]),
            {"done": True, "content": "light rain"},
        )
        children = self._children(root)
        self.assertEqual(
            sorted(s.name for s in children), ["llm", "llm", "tool:ecmwf_fetch"]
        )
        self.assertEqual(len(self._spans()), 4)
        for span in children:
            self.assertEqual(span.context.trace_id, root.context.trace_id)
            self.assertLessEqual(span.end_time, root.end_time)
        self.assertIsNone(lf.current_trace())
        self.chats.upsert_message_to_chat_by_id_and_message_id.assert_called_once_with(
            "chat-auto", "msg-auto", {"done": True}
        )

    async def test_model_call_failure_ends_root_with_error(self):
        self.handler_error = RuntimeError("provider down")

        with self._no_otel_complaints():
            with self.assertRaises(RuntimeError) as raised:
                await self._run()
        self._flush()

        self.assertIs(raised.exception, self.handler_error)
        root = self._assert_error_root("provider down")
        (generation,) = self._children(root)
        self.assertEqual(generation.attributes[A.OBSERVATION_LEVEL], "ERROR")
        self.assertIsNone(lf.current_trace())
        self.chats.upsert_message_to_chat_by_id_and_message_id.assert_not_called()

    async def test_tool_loop_failure_ends_root_with_error(self):
        async def loop_crash():
            tool = lf.start_tool_observation("ecmwf_fetch", {})
            lf.end_tool_observation(tool, error="boom")
            raise RuntimeError("tool loop crashed")

        self.loop_body = loop_crash

        with self._no_otel_complaints():
            with self.assertRaises(RuntimeError):
                await self._run()
        self._flush()

        root = self._assert_error_root("tool loop crashed")
        self.assertEqual(
            sorted(s.name for s in self._children(root)), ["llm", "tool:ecmwf_fetch"]
        )
        self.assertIsNone(lf.current_trace())

    async def test_failure_after_loop_ended_root_is_logged_not_attached(self):
        async def loop_end_then_crash():
            lf.end_chat_trace(output={"done": True, "content": "light rain"})
            raise RuntimeError("late failure")

        self.loop_body = loop_end_then_crash

        with self._no_otel_complaints():
            with self.assertLogs(automation_runner.log, level="DEBUG") as logs:
                with self.assertRaises(RuntimeError):
                    await self._run()
        self._flush()

        root = self._root()
        self.assertNotIn(A.OBSERVATION_LEVEL, root.attributes)
        self.assertEqual(
            json.loads(root.attributes[A.OBSERVATION_OUTPUT]),
            {"done": True, "content": "light rain"},
        )
        self.assertTrue(
            any("late failure" in line for line in logs.output), logs.output
        )
        self.assertIsNone(lf.current_trace())

    async def test_non_streaming_result_is_the_root_output(self):
        async def process_response(*args):
            return {"choices": [{"message": {"content": "light rain"}}]}

        with patch.object(automation_runner, "process_chat_response", process_response):
            with self._no_otel_complaints():
                await self._run()
        self._flush()

        root = self._root()
        self.assertNotIn(A.OBSERVATION_LEVEL, root.attributes)
        self.assertEqual(
            json.loads(root.attributes[A.OBSERVATION_OUTPUT]),
            {"content": "light rain"},
        )
        self.assertEqual([s.name for s in self._children(root)], ["llm"])
        self.assertIsNone(lf.current_trace())

    async def test_missing_loop_task_still_ends_root(self):
        async def process_response(*args):
            return {"status": True, "task_id": "not-registered"}

        with patch.object(automation_runner, "process_chat_response", process_response):
            with self._no_otel_complaints():
                await self._run()
        self._flush()

        root = self._root()
        self.assertNotIn(A.OBSERVATION_LEVEL, root.attributes)
        self.assertNotIn(A.OBSERVATION_OUTPUT, root.attributes)
        self.assertIsNone(lf.current_trace())
        self.chats.upsert_message_to_chat_by_id_and_message_id.assert_called_once_with(
            "chat-auto", "msg-auto", {"done": True}
        )

    async def test_base_exception_ends_root_with_that_error(self):
        class Stop(BaseException):
            pass

        async def payload_raises(*args):
            raise Stop("worker shutting down")

        with patch.object(automation_runner, "process_chat_payload", payload_raises):
            with self._no_otel_complaints():
                with self.assertRaises(Stop):
                    await self._run()
        self._flush()

        self._assert_error_root("worker shutting down")
        self.assertIsNone(lf.current_trace())

    async def test_cancel_during_tool_loop_ends_root_once(self):
        async def loop_until_cancelled():
            self.loop_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                lf.end_chat_trace(error="cancelled")

        self.loop_body = loop_until_cancelled

        with self._no_otel_complaints():
            run = asyncio.create_task(self._run())
            await self.loop_started.wait()
            run.cancel()
            # Cancelling the run cancels the awaited loop task. The loop
            # handles it, as the middleware does, so the run returns.
            await run
        self._flush()

        self._assert_error_root("cancelled")
        self.assertIsNone(lf.current_trace())

    async def test_cancel_before_tool_loop_ends_root(self):
        async def payload_until_cancelled(*args):
            self.loop_started.set()
            await asyncio.Event().wait()

        with patch.object(
            automation_runner, "process_chat_payload", payload_until_cancelled
        ), self._no_otel_complaints():
            run = asyncio.create_task(self._run())
            await self.loop_started.wait()
            run.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await run
        self._flush()

        root = self._assert_error_root("cancelled")
        self.assertEqual(self._children(root), [])

    async def test_tracing_disabled_runs_unchanged_and_records_nothing(self):
        with patch.object(lf, "LANGFUSE_ENABLED", False):
            await self._run()
        self._flush()

        self.assertEqual(self._spans(), ())
        self.chats.upsert_message_to_chat_by_id_and_message_id.assert_called_once_with(
            "chat-auto", "msg-auto", {"done": True}
        )


if __name__ == "__main__":
    unittest.main()
