"""A model call that the provider answers with a short-wait 429 is resent after the wait."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from open_webui.routers import openai as openai_router


class _FakeResponse:
    def __init__(self, status, body, headers=None):
        self.status = status
        self.body = body
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.closed = False

    async def json(self):
        return self.body

    async def text(self):
        return str(self.body)

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status}")

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, responses, sent):
        self.responses = responses
        self.sent = sent

    async def request(self, **kwargs):
        self.sent.append(kwargs)
        return self.responses.pop(0)

    async def close(self):
        pass


def _admission_429(retry_after="10", in_header=True):
    body = {
        "error": {
            "message": "OpenRouter could not verify available credits for this request in time. Retry shortly.",
            "code": 429,
            "metadata": {
                "limit_source": "openrouter_admission_control",
                "headers": {"Retry-After": retry_after},
                "provider_name": None,
            },
        }
    }
    headers = {"Retry-After": retry_after} if in_header else {}
    return _FakeResponse(429, body, headers)


def _ok():
    return _FakeResponse(200, {"choices": [{"message": {"content": "Rain outlook"}}]})


class Provider429RetryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sent = []
        self.slept = []
        self.responses = []
        self.user = SimpleNamespace(
            id="uid-1", email="a@example.com", name="A", role="user"
        )

        async def fake_sleep(seconds):
            self.slept.append(seconds)

        self.patches = [
            patch.object(
                openai_router,
                "prepare_provider_call",
                return_value=("https://openrouter.ai/api/v1", "key", "{}", "chat-1"),
            ),
            patch.object(
                openai_router.aiohttp,
                "ClientSession",
                side_effect=lambda **kwargs: _FakeSession(self.responses, self.sent),
            ),
            patch.object(openai_router.asyncio, "sleep", side_effect=fake_sleep),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()

    async def _call(self):
        return await openai_router.generate_chat_completion(
            SimpleNamespace(), {"model": "m"}, self.user, bypass_filter=True
        )

    async def test_short_retry_after_is_waited_and_resent(self):
        first = _admission_429("10")
        self.responses += [first, _ok()]

        response = await self._call()

        self.assertEqual(response["choices"][0]["message"]["content"], "Rain outlook")
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.slept, [10])
        self.assertTrue(first.closed)

    async def test_retry_after_only_in_body_is_honored(self):
        self.responses += [_admission_429("3", in_header=False), _ok()]

        response = await self._call()

        self.assertEqual(response["choices"][0]["message"]["content"], "Rain outlook")
        self.assertEqual(self.slept, [3])

    async def test_gives_up_after_two_retries(self):
        self.responses += [_admission_429(), _admission_429(), _admission_429()]

        with self.assertRaises(HTTPException) as caught:
            await self._call()

        self.assertEqual(caught.exception.status_code, 429)
        self.assertIn("could not verify available credits", caught.exception.detail)
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(self.slept, [10, 10])

    async def test_long_retry_after_fails_without_waiting(self):
        self.responses += [_admission_429("60")]

        with self.assertRaises(HTTPException) as caught:
            await self._call()

        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.slept, [])

    async def test_429_without_retry_after_fails_without_waiting(self):
        response = _FakeResponse(429, {"error": {"message": "Rate limited"}})
        self.responses += [response]

        with self.assertRaises(HTTPException):
            await self._call()

        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.slept, [])

    async def test_other_errors_are_not_retried(self):
        self.responses += [_FakeResponse(500, {"error": {"message": "boom"}})]

        with self.assertRaises(HTTPException) as caught:
            await self._call()

        self.assertEqual(caught.exception.status_code, 500)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.slept, [])


if __name__ == "__main__":
    unittest.main()
