"""Each model call checks caps and access, reads its tracing style, builds its request and records usage off the event loop."""

import asyncio
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from starlette.responses import StreamingResponse

from open_webui.routers import openai as openai_router
from open_webui.utils import chat, usage
from open_webui.utils.langfuse_tracing import MODEL_CALL_TRACING_APP


class _FakeResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    async def json(self):
        return {
            "choices": [{"message": {"content": "Rain outlook"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2},
        }

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


def _request():
    config = SimpleNamespace(
        OPENAI_API_BASE_URLS=["https://provider.test/v1"],
        OPENAI_API_KEYS=["key"],
        OPENAI_API_CONFIGS={"0": {}},
    )
    models = {"weather-agent": {"id": "weather-agent", "owned_by": "openai"}}
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=config, MODELS=models)),
        state=SimpleNamespace(),
        headers={},
    )


def _model_row():
    return SimpleNamespace(
        base_model_id=None, params=SimpleNamespace(model_dump=lambda: {})
    )


def _form():
    return {
        "model": "weather-agent",
        "messages": [{"role": "user", "content": "Rain this week?"}],
        "stream": False,
        "metadata": {"chat_id": "chat-1", "organization_id": "org-1"},
    }


class ModelCallThreadsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.loop_thread = threading.current_thread()
        self.ran_on = {}
        self.sent = []
        self.hops = []
        real_to_thread = asyncio.to_thread

        async def to_thread(func, *args, **kwargs):
            self.hops.append(func.__name__)
            return await real_to_thread(func, *args, **kwargs)

        def on(name, result=None):
            def record(*args, **kwargs):
                self.ran_on[name] = threading.current_thread()
                return result

            return record

        self.check_model_access = patch.object(
            chat, "check_model_access", side_effect=on("access")
        )
        self.patches = [
            patch.object(chat, "enforce_usage_caps", side_effect=on("caps")),
            self.check_model_access,
            patch.object(
                openai_router.Models,
                "get_model_by_id",
                side_effect=on("router_model", _model_row()),
            ),
            patch(
                "open_webui.models.organizations.Organizations.user_organization_ids",
                return_value=["org-1"],
            ),
            patch("open_webui.utils.catalog.is_usable", return_value=True),
            patch.object(
                usage, "record_provider_usage", autospec=True, side_effect=on("usage")
            ),
            patch.object(
                openai_router.aiohttp,
                "ClientSession",
                side_effect=lambda **kwargs: _FakeSession(self.sent),
            ),
            patch.object(chat, "tracing_enabled", return_value=True),
            patch.object(
                chat,
                "model_call_tracing_style_for_model",
                side_effect=on("style", MODEL_CALL_TRACING_APP),
            ),
            patch.object(asyncio, "to_thread", to_thread),
        ]
        self.mocks = [p.start() for p in self.patches]

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def _user(self, role="user"):
        return SimpleNamespace(id="u1", email="u1@example.com", name="U", role=role)

    async def test_checks_request_build_and_usage_run_on_worker_threads(self):
        response = await chat.generate_chat_completion(
            _request(), _form(), self._user()
        )

        self.assertEqual(response["choices"][0]["message"]["content"], "Rain outlook")
        self.assertEqual(
            set(self.ran_on), {"caps", "access", "style", "router_model", "usage"}
        )
        for name, thread in self.ran_on.items():
            self.assertIsNot(thread, self.loop_thread, name)
        # One hop checks caps and access and reads the style, the router
        # builds the request in a second, and the usage write is the third.
        self.assertEqual(
            self.hops,
            ["authorize_model_call", "prepare_provider_call", "record_provider_usage"],
        )
        self.assertEqual(self.sent[0]["model"], "weather-agent")

    async def test_a_user_without_access_never_reaches_the_provider(self):
        self.mocks[1].side_effect = Exception("Model not found")
        with self.assertRaisesRegex(Exception, "Model not found"):
            await chat.generate_chat_completion(_request(), _form(), self._user())
        self.assertEqual(self.sent, [])

    async def test_admins_are_not_access_checked(self):
        await chat.generate_chat_completion(_request(), _form(), self._user("admin"))
        self.mocks[1].assert_not_called()
        self.assertIn("caps", self.ran_on)

    async def test_usage_at_the_end_of_a_stream_is_recorded_on_a_worker_thread(self):
        async def body():
            yield b'data: {"choices": [{"delta": {"content": "Rain"}}]}\n\n'
            yield b'data: {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}\n\n'
            yield b"data: [DONE]\n\n"

        response = await usage.bind_usage_to_response(
            StreamingResponse(body(), media_type="text/event-stream"), {"user_id": "u1"}
        )
        chunks = [chunk async for chunk in response.body_iterator]

        self.assertEqual(len(chunks), 3)
        self.assertIsNot(self.ran_on["usage"], self.loop_thread)


if __name__ == "__main__":
    unittest.main()
