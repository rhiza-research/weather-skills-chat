"""A model with a backup is resent to the backup when its provider fails before replying."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
from fastapi import HTTPException

from open_webui.models.usage import parse_provider_usage
from open_webui.routers import openai as openai_router

PRIMARY = "https://openrouter.ai/api/v1"
BACKUP = "https://router.requesty.ai/v1"


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
    def __init__(self, replies, sent):
        self.replies = replies
        self.sent = sent

    async def request(self, **kwargs):
        url = kwargs["url"].removesuffix("/chat/completions")
        self.sent.append((url, json.loads(kwargs["data"])["model"]))
        reply = self.replies[url].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


    async def close(self):
        pass


def _ok(text="Rain outlook"):
    return _FakeResponse(200, {"choices": [{"message": {"content": text}}]})


def _error(status, message="upstream failed", headers=None):
    return _FakeResponse(status, {"error": {"message": message}}, headers)


def _fake_prepare(fallback):
    """Stand-in for prepare_provider_call: the wrapper forwards to PRIMARY."""

    def prepare(request, form_data, user, bypass_filter, upstream_model_id=None):
        if upstream_model_id is None:
            return openai_router.ProviderCall(
                url=PRIMARY,
                key="k1",
                payload=json.dumps({"model": "anthropic/claude-sonnet-4.5"}),
                chat_id="chat-1",
                url_idx=0,
                fallback_model_id=fallback,
            )
        return openai_router.ProviderCall(
            url=BACKUP,
            key="k2",
            payload=json.dumps({"model": upstream_model_id}),
            chat_id="chat-1",
            url_idx=1,
            fallback_model_id=None,
        )

    return prepare


class ProviderFallbackTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sent = []
        self.replies = {PRIMARY: [], BACKUP: []}
        self.user = SimpleNamespace(
            id="uid-1", email="a@example.com", name="A", role="user"
        )
        openai_router._provider_down_until.clear()

        self.prepare = patch.object(
            openai_router,
            "prepare_provider_call",
            side_effect=_fake_prepare("requesty.anthropic/claude-sonnet-4-5"),
        )
        self.patches = [
            self.prepare,
            patch.object(
                openai_router.aiohttp,
                "ClientSession",
                side_effect=lambda **kwargs: _FakeSession(self.replies, self.sent),
            ),
        ]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()
        openai_router._provider_down_until.clear()

    def _lapse(self, url):
        openai_router._provider_down_until[url] = 0.0

    def _without_backup(self):
        openai_router.prepare_provider_call.side_effect = _fake_prepare(None)

    async def _call(self, request=None):
        return await openai_router.generate_chat_completion(
            request or SimpleNamespace(state=SimpleNamespace()),
            {"model": "weather-agent"},
            self.user,
            bypass_filter=True,
        )

    async def test_server_error_is_resent_to_the_backup(self):
        self.replies[PRIMARY] += [_error(503)]
        self.replies[BACKUP] += [_ok("From backup")]

        response = await self._call()

        self.assertEqual(response["choices"][0]["message"]["content"], "From backup")
        self.assertEqual(
            self.sent,
            [
                (PRIMARY, "anthropic/claude-sonnet-4.5"),
                (BACKUP, "requesty.anthropic/claude-sonnet-4-5"),
            ],
        )

    async def test_connection_error_is_resent_to_the_backup(self):
        self.replies[PRIMARY] += [aiohttp.ClientConnectionError("refused")]
        self.replies[BACKUP] += [_ok("From backup")]

        response = await self._call()

        self.assertEqual(response["choices"][0]["message"]["content"], "From backup")

    async def test_out_of_credits_is_resent_to_the_backup(self):
        self.replies[PRIMARY] += [_error(402, "Insufficient credits")]
        self.replies[BACKUP] += [_ok()]

        await self._call()

        self.assertEqual([url for url, _ in self.sent], [PRIMARY, BACKUP])

    async def test_rate_limit_is_resent_to_the_backup(self):
        self.replies[PRIMARY] += [_error(429, "Rate limited")]
        self.replies[BACKUP] += [_ok()]

        await self._call()

        self.assertEqual([url for url, _ in self.sent], [PRIMARY, BACKUP])

    async def test_rejected_key_is_resent_to_the_backup(self):
        self.replies[PRIMARY] += [_error(401, "Missing Authentication header")]
        self.replies[BACKUP] += [_ok()]

        await self._call()

        self.assertEqual([url for url, _ in self.sent], [PRIMARY, BACKUP])

    async def test_spent_key_limit_is_resent_and_marks_the_primary_down(self):
        self.replies[PRIMARY] += [_error(403, "Key limit exceeded (monthly limit)")]
        self.replies[BACKUP] += [_ok(), _ok()]

        await self._call()
        await self._call()

        self.assertEqual([url for url, _ in self.sent], [PRIMARY, BACKUP, BACKUP])

    async def test_rejected_request_is_resent_but_does_not_mark_the_primary_down(self):
        self.replies[PRIMARY] += [_error(400, "Bad request"), _ok()]
        self.replies[BACKUP] += [_ok()]

        await self._call()
        await self._call()

        self.assertEqual([url for url, _ in self.sent], [PRIMARY, BACKUP, PRIMARY])

    async def test_request_rejected_by_both_raises_the_primary_error(self):
        self.replies[PRIMARY] += [_error(400, "Prompt is too long")]
        self.replies[BACKUP] += [_error(400, "Context length exceeded")]

        with self.assertRaises(HTTPException) as caught:
            await self._call()

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("Prompt is too long", caught.exception.detail)

    async def test_model_without_backup_fails_as_before(self):
        self._without_backup()
        self.replies[PRIMARY] += [_error(503)]

        with self.assertRaises(HTTPException) as caught:
            await self._call()

        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual([url for url, _ in self.sent], [PRIMARY])

    async def test_when_both_fail_the_primary_error_is_raised(self):
        self.replies[PRIMARY] += [_error(503, "primary down")]
        self.replies[BACKUP] += [_error(502, "backup down")]

        with self.assertRaises(HTTPException) as caught:
            await self._call()

        self.assertEqual(caught.exception.status_code, 503)
        self.assertIn("primary down", caught.exception.detail)

    async def test_rest_of_the_reply_stays_on_the_backup(self):
        request = SimpleNamespace(state=SimpleNamespace())
        self.replies[PRIMARY] += [_error(503)]
        self.replies[BACKUP] += [_ok(), _ok()]

        await self._call(request)
        # The primary's down marker lapses, but this reply has switched.
        self._lapse(PRIMARY)
        await self._call(request)

        self.assertEqual([url for url, _ in self.sent], [PRIMARY, BACKUP, BACKUP])

    async def test_next_reply_skips_a_down_primary_until_the_marker_lapses(self):
        self.replies[PRIMARY] += [_error(503), _ok()]
        self.replies[BACKUP] += [_ok(), _ok()]

        await self._call()
        await self._call()
        self._lapse(PRIMARY)
        await self._call()

        self.assertEqual(
            [url for url, _ in self.sent], [PRIMARY, BACKUP, BACKUP, PRIMARY]
        )

    async def test_model_without_backup_still_tries_a_down_primary(self):
        self.replies[PRIMARY] += [_error(503), _ok("Primary again")]
        self.replies[BACKUP] += [_ok()]

        await self._call()
        self._without_backup()
        response = await self._call()

        self.assertEqual(response["choices"][0]["message"]["content"], "Primary again")
        self.assertEqual([url for url, _ in self.sent], [PRIMARY, BACKUP, PRIMARY])

    async def test_failing_backup_falls_back_to_the_primary(self):
        request = SimpleNamespace(state=SimpleNamespace())
        self.replies[PRIMARY] += [_error(503), _ok("Primary recovered")]
        self.replies[BACKUP] += [_ok(), _error(503)]

        await self._call(request)
        response = await self._call(request)

        self.assertEqual(
            response["choices"][0]["message"]["content"], "Primary recovered"
        )
        self.assertEqual(
            [url for url, _ in self.sent], [PRIMARY, BACKUP, BACKUP, PRIMARY]
        )

    async def test_backup_whose_connection_is_gone_raises_the_primary_error(self):
        def prepare(request, form_data, user, bypass_filter, upstream_model_id=None):
            if upstream_model_id:
                raise HTTPException(status_code=404, detail="Model not found")
            return _fake_prepare("requesty.gone")(request, form_data, user, bypass_filter)

        openai_router.prepare_provider_call.side_effect = prepare
        self.replies[PRIMARY] += [_error(503, "primary down")]

        with self.assertRaises(HTTPException) as caught:
            await self._call()

        self.assertEqual(caught.exception.status_code, 503)


def _app_request(urls, configs):
    config = SimpleNamespace(
        OPENAI_API_BASE_URLS=urls,
        OPENAI_API_KEYS=[f"key-{i}" for i in range(len(urls))],
        OPENAI_API_CONFIGS=configs,
    )
    return SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(config=config)),
        state=SimpleNamespace(),
    )


TWO_CONNECTIONS = (
    [PRIMARY, BACKUP],
    {"0": {"enable": True}, "1": {"enable": True, "prefix_id": "requesty"}},
)


class PrepareBackupCallTest(unittest.TestCase):
    def _wrapper(self, fallback):
        return SimpleNamespace(
            base_model_id="anthropic/claude-sonnet-4.5",
            params=SimpleNamespace(model_dump=lambda: {"system": "Be brief."}),
            meta=SimpleNamespace(fallback_model_id=fallback),
        )

    def _prepare(self, upstream_model_id=None):
        request = _app_request(*TWO_CONNECTIONS)
        form = {
            "model": "weather-agent",
            "messages": [{"role": "user", "content": "Rain?"}],
        }
        with patch.object(
            openai_router.Models,
            "get_model_by_id",
            return_value=self._wrapper("requesty.anthropic/claude-sonnet-4-5"),
        ):
            return openai_router.prepare_provider_call(
                request, form, None, True, upstream_model_id=upstream_model_id
            )

    def test_primary_call_carries_the_wrappers_backup(self):
        call = self._prepare()

        self.assertEqual(call.url, PRIMARY)
        self.assertEqual(call.url_idx, 0)
        self.assertEqual(call.fallback_model_id, "requesty.anthropic/claude-sonnet-4-5")
        self.assertEqual(json.loads(call.payload)["model"], "anthropic/claude-sonnet-4.5")

    def test_backup_call_goes_to_the_backup_connection_with_the_wrapper_prompt(self):
        call = self._prepare("requesty.anthropic/claude-sonnet-4-5")
        payload = json.loads(call.payload)

        self.assertEqual(call.url, BACKUP)
        self.assertEqual(call.key, "key-1")
        self.assertIsNone(call.fallback_model_id)
        self.assertEqual(payload["model"], "anthropic/claude-sonnet-4-5")
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "Be brief."})


class ConnectionPrefixTest(unittest.TestCase):
    def test_prefixed_id_goes_to_its_connection_whatever_the_order(self):
        for urls, configs, expected in [
            (*TWO_CONNECTIONS, 1),
            (
                [BACKUP, PRIMARY],
                {"0": {"prefix_id": "requesty"}, "1": {"enable": True}},
                0,
            ),
        ]:
            request = _app_request(urls, configs)
            self.assertEqual(
                openai_router.connection_index_for_model(
                    request, "requesty.anthropic/claude-sonnet-4-5"
                ),
                expected,
            )

    def test_unprefixed_id_is_not_sent_to_a_prefixed_connection(self):
        request = _app_request(*TWO_CONNECTIONS)
        self.assertEqual(
            openai_router.connection_index_for_model(
                request, "anthropic/claude-sonnet-4.5"
            ),
            0,
        )


class FallbackModelCheckTest(unittest.TestCase):
    def setUp(self):
        self.request = _app_request(*TWO_CONNECTIONS)

    def check(self, base, fallback):
        return openai_router.fallback_model_error(self.request, base, fallback)

    def test_backup_on_another_connection_is_accepted(self):
        self.assertIsNone(
            self.check("anthropic/claude-sonnet-4.5", "requesty.anthropic/claude-sonnet-4-5")
        )

    def test_no_backup_is_accepted(self):
        self.assertIsNone(self.check("anthropic/claude-sonnet-4.5", None))

    def test_backup_on_the_same_connection_is_refused(self):
        self.assertIsNotNone(
            self.check("anthropic/claude-sonnet-4.5", "openai/gpt-5")
        )

    def test_backup_with_no_connection_is_refused(self):
        request = _app_request(
            [PRIMARY, BACKUP],
            {"0": {"model_ids": ["anthropic/claude-sonnet-4.5"]}, "1": {"enable": False}},
        )
        self.assertIsNotNone(
            openai_router.fallback_model_error(
                request, "anthropic/claude-sonnet-4.5", "requesty.anthropic/claude-sonnet-4-5"
            )
        )


def test_connection_name_is_the_admins_name_else_the_host():
    request = _app_request(
        [PRIMARY, BACKUP], {"0": {}, "1": {"name": " requesty "}}
    )
    assert openai_router.connection_name(request, 0) == "openrouter.ai"
    assert openai_router.connection_name(request, 1) == "requesty"


def test_requesty_usage_cost_is_read_in_usd():
    # Shape from Requesty's API reference: cost in USD inside usage.
    parsed = parse_provider_usage(
        {
            "prompt_tokens": 120,
            "completion_tokens": 30,
            "total_tokens": 150,
            "cost": 0.000325,
        }
    )
    assert parsed["has_cost"] is True
    assert parsed["cost_usd"] == 0.000325
    assert parsed["prompt_tokens"] == 120
    assert parsed["completion_tokens"] == 30


if __name__ == "__main__":
    unittest.main()
