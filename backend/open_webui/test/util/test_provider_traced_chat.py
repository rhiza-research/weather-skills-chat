"""Model calls through utils.chat (the title/tag task path) to the OpenAI router."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from open_webui.routers import openai as openai_router
from open_webui.utils import chat
from open_webui.utils import langfuse_tracing as lf


class _FakeResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    async def json(self):
        return {"choices": [{"message": {"content": "Rain outlook"}}]}

    def raise_for_status(self):
        pass

    def close(self):
        pass


class _FakeSession:
    def __init__(self, sent):
        self.sent = sent

    async def request(self, **kwargs):
        self.sent.append(json.loads(kwargs["data"]))
        return _FakeResponse()

    async def close(self):
        pass


def _request(style):
    config = SimpleNamespace(
        OPENAI_API_BASE_URLS=["https://openrouter.ai/api/v1"],
        OPENAI_API_KEYS=["key"],
        OPENAI_API_CONFIGS={"0": {"model_call_tracing": style}},
    )
    models = {"openai/gpt-4o": {"id": "openai/gpt-4o", "owned_by": "openai"}}
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=config, MODELS=models)),
        state=SimpleNamespace(),
        headers={},
    )


class TitleCallThroughChatTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        lf._trace_var.set(None)
        lf._trace_metadata_var.set(None)
        lf._generation_stack_var.set(None)
        self.root = MagicMock(trace_id="c" * 32, id="d" * 16)
        lf._trace_var.set(self.root)
        lf._trace_metadata_var.set(
            {"chat_id": "chat-1", "message_id": "msg-1", "model": "weather-agent"}
        )
        self.user = SimpleNamespace(
            id="uid-99", email="bob@example.com", name="Bob", role="admin"
        )
        self.sent = []
        self.patches = [
            patch.object(lf, "tracing_enabled", return_value=True),
            patch.object(chat, "tracing_enabled", return_value=True),
            patch.object(openai_router, "tracing_enabled", return_value=True),
            patch.object(openai_router.Models, "get_model_by_id", return_value=None),
            patch.object(
                openai_router.aiohttp,
                "ClientSession",
                side_effect=lambda **kwargs: _FakeSession(self.sent),
            ),
            patch.object(chat, "enforce_usage_caps"),
            patch.object(chat, "resolve_usage_context"),
            patch.object(chat, "bind_usage_to_response", side_effect=lambda r, c: r),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        lf._trace_var.set(None)
        lf._trace_metadata_var.set(None)
        lf._generation_stack_var.set(None)

    def _title_form(self):
        return {
            "model": "openai/gpt-4o",
            "messages": [{"role": "user", "content": "Generate a title"}],
            "stream": False,
            "metadata": {"task": "title_generation", "chat_id": "chat-1"},
        }

    async def test_openrouter_title_call_nests_under_root_span(self):
        response = await chat.generate_chat_completion(
            _request("openrouter"), self._title_form(), self.user
        )

        self.assertEqual(response["choices"][0]["message"]["content"], "Rain outlook")
        self.root.start_observation.assert_not_called()
        body = self.sent[0]
        self.assertEqual(body["trace"]["trace_id"], "c" * 32)
        self.assertEqual(body["trace"]["parent_span_id"], "d" * 16)
        self.assertEqual(body["trace"]["generation_name"], "llm")
        self.assertEqual(body["user"], "bob@example.com")
        self.assertEqual(body["session_id"], "chat-1")
        self.assertNotIn("metadata", body)

    async def test_style_decision_error_records_app_generation_only(self):
        with patch.object(
            chat,
            "model_call_tracing_style_for_model",
            side_effect=RuntimeError("config read failed"),
        ):
            await chat.generate_chat_completion(
                _request("openrouter"), self._title_form(), self.user
            )

        self.assertEqual(
            self.root.start_observation.call_args.kwargs["as_type"], "generation"
        )
        body = self.sent[0]
        for key in ("trace", "user"):
            self.assertNotIn(key, body)

    async def test_stale_style_in_reused_metadata_is_dropped(self):
        form = self._title_form()
        form["metadata"]["model_call_tracing"] = "openrouter"
        await chat.generate_chat_completion(_request("app"), form, self.user)

        self.assertEqual(
            self.root.start_observation.call_args.kwargs["as_type"], "generation"
        )
        self.assertNotIn("trace", self.sent[0])


    async def test_shared_state_metadata_never_gains_style(self):
        request = _request("openrouter")
        shared = {"task": "title_generation", "chat_id": "chat-1"}
        request.state.metadata = shared
        form = self._title_form()
        form["metadata"] = shared

        await chat.generate_chat_completion(request, form, self.user)
        self.assertNotIn("model_call_tracing", shared)
        self.assertIn("trace", self.sent[0])
        self.root.start_observation.assert_not_called()

        request.app.state.config.OPENAI_API_CONFIGS = {"0": {}}
        await chat.generate_chat_completion(request, form, self.user)
        self.assertNotIn("model_call_tracing", shared)
        self.assertEqual(
            self.root.start_observation.call_args.kwargs["as_type"], "generation"
        )
        for key in ("trace", "user"):
            self.assertNotIn(key, self.sent[1])

        # A task that copies request.state.metadata into a fresh form.
        await chat.generate_chat_completion(
            request, {**self._title_form(), "metadata": dict(shared)}, self.user
        )
        self.assertNotIn("model_call_tracing", shared)
        for key in ("trace", "user"):
            self.assertNotIn(key, self.sent[2])


class RouterProviderFieldsTest(unittest.IsolatedAsyncioTestCase):
    """The router adds provider fields only when the carried style and the
    serving connection's configured style are the same provider style."""

    async def asyncSetUp(self):
        lf._trace_var.set(MagicMock(trace_id="c" * 32, id="d" * 16))
        lf._trace_metadata_var.set({"chat_id": "chat-1"})
        self.user = SimpleNamespace(
            id="uid-99", email="bob@example.com", name="Bob", role="admin"
        )
        self.sent = []
        self.patches = [
            patch.object(lf, "tracing_enabled", return_value=True),
            patch.object(openai_router.Models, "get_model_by_id", return_value=None),
            patch.object(
                openai_router.aiohttp,
                "ClientSession",
                side_effect=lambda **kwargs: _FakeSession(self.sent),
            ),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        lf._trace_var.set(None)
        lf._trace_metadata_var.set(None)

    async def _send(self, connection_style, carried_style, top_level=False):
        form = {
            "model": "openai/gpt-4o",
            "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"chat_id": "chat-1", "model_call_tracing": carried_style},
        }
        if top_level:
            form["model_call_tracing"] = carried_style
        await openai_router.generate_chat_completion(
            _request(connection_style), form, user=self.user
        )
        body = self.sent[-1]
        self.assertNotIn("model_call_tracing", body)
        self.assertNotIn("metadata", body)
        return body

    async def test_direct_call_injected_style_on_app_connection_adds_nothing(self):
        body = await self._send("app", "openrouter", top_level=True)
        for key in ("trace", "user"):
            self.assertNotIn(key, body)

    async def test_carried_openrouter_on_app_connection_adds_nothing(self):
        body = await self._send("app", "openrouter")
        for key in ("trace", "user"):
            self.assertNotIn(key, body)

    async def test_carried_app_on_openrouter_connection_adds_nothing(self):
        body = await self._send("openrouter", "app")
        for key in ("trace", "user"):
            self.assertNotIn(key, body)

    async def test_both_openrouter_adds_fields(self):
        body = await self._send("openrouter", "openrouter")
        self.assertEqual(body["trace"]["trace_id"], "c" * 32)
        self.assertEqual(body["trace"]["parent_span_id"], "d" * 16)
        self.assertEqual(body["user"], "bob@example.com")


if __name__ == "__main__":
    unittest.main()
