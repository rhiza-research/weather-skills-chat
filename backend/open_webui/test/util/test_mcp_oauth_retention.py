"""Deleting unusable authorization rows, and the per-IP limits on register and authorize."""

import asyncio
import secrets
import time
import unittest
import uuid
from unittest.mock import patch

from open_webui.mcp_oauth.limits import (
    AUTHORIZE_LIMIT,
    REGISTER_LIMIT,
    RateLimiter,
)
from open_webui.internal.db import get_db
from open_webui.mcp_oauth import retention
from open_webui.mcp_oauth.retention import IDLE_CLIENT_SECONDS, purge_once
from open_webui.models.mcp_oauth import (
    ACCESS,
    REFRESH,
    McpOAuth,
    McpOAuthAuthorization,
    McpOAuthClient,
    McpOAuthCode,
    McpOAuthToken,
    digest,
)
from open_webui.test.util.test_mcp_oauth import (
    IDENTIFIER,
    REDIRECT_URI,
    EndpointCase,
    new_account,
)


def row_exists(model, **key):
    with get_db() as db:
        return db.query(model).filter_by(**key).first() is not None


def token(kind, client_id, *, expires_in, revoked=False, user_id=None):
    value = secrets.token_urlsafe(32)
    McpOAuth.insert_token(
        value,
        kind=kind,
        grant_id=str(uuid.uuid4()),
        client_id=client_id,
        user_id=user_id or new_account(),
        scopes=[],
        resource=IDENTIFIER,
        expires_at=int(time.time()) + expires_in,
    )
    if revoked:
        McpOAuth.revoke_grant(value)
    return value


def code(client_id, *, expires_in):
    value = secrets.token_urlsafe(32)
    McpOAuth.insert_code(
        value,
        client_id=client_id,
        user_id=new_account(),
        redirect_uri=REDIRECT_URI,
        redirect_uri_provided_explicitly=True,
        code_challenge="c",
        scopes=[],
        resource=IDENTIFIER,
        expires_at=int(time.time()) + expires_in,
    )
    return value


def pending(client_id, *, expires_in):
    value = secrets.token_urlsafe(32)
    McpOAuth.insert_authorization(
        value,
        client_id=client_id,
        redirect_uri=REDIRECT_URI,
        redirect_uri_provided_explicitly=True,
        state=None,
        code_challenge="c",
        scopes=[],
        resource=IDENTIFIER,
        expires_at=int(time.time()) + expires_in,
    )
    return value


class PurgeTest(EndpointCase):
    def test_expired_rows_are_deleted_and_live_rows_kept(self):
        client_id = self.flow.registered_client_id()
        expired = {
            "access": token(ACCESS, client_id, expires_in=-1),
            "refresh": token(REFRESH, client_id, expires_in=-1),
            "code": code(client_id, expires_in=-1),
            "request": pending(client_id, expires_in=-1),
        }
        live = {
            "access": token(ACCESS, client_id, expires_in=600),
            "refresh": token(REFRESH, client_id, expires_in=600),
            "code": code(client_id, expires_in=600),
            "request": pending(client_id, expires_in=600),
        }
        purge_once()
        for rows, kept in ((expired, False), (live, True)):
            self.assertEqual(
                row_exists(McpOAuthToken, token_hash=digest(rows["access"])), kept
            )
            self.assertEqual(
                row_exists(McpOAuthToken, token_hash=digest(rows["refresh"])), kept
            )
            self.assertEqual(row_exists(McpOAuthCode, code_hash=digest(rows["code"])), kept)
            self.assertEqual(
                row_exists(McpOAuthAuthorization, request_hash=digest(rows["request"])), kept
            )

    def test_a_revoked_access_token_is_deleted(self):
        client_id = self.flow.registered_client_id()
        value = token(ACCESS, client_id, expires_in=600, revoked=True)
        purge_once()
        self.assertFalse(row_exists(McpOAuthToken, token_hash=digest(value)))

    def test_a_decided_request_is_deleted(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(new_account())
        self.flow.decide(self.flow.form_fields(self.flow.consent_page(request_id)), "deny")
        purge_once()
        self.assertFalse(row_exists(McpOAuthAuthorization, request_hash=digest(request_id)))

    def test_a_used_code_is_kept_until_it_expires_so_a_replay_still_revokes(self):
        client_id = self.flow.registered_client_id()
        issued = self.flow.code(client_id, new_account())
        tokens = self.flow.exchange(client_id, issued).json()
        purge_once()
        self.flow.exchange(client_id, issued)
        self.assertEqual(self.flow.mcp_initialize(tokens["access_token"]).status_code, 401)

    def test_a_rotated_refresh_token_is_kept_until_it_expires(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        rotated = self.flow.refresh(client_id, tokens["refresh_token"]).json()
        purge_once()
        self.flow.refresh(client_id, tokens["refresh_token"])
        self.assertEqual(self.flow.mcp_initialize(rotated["access_token"]).status_code, 401)


class IdleClientTest(EndpointCase):
    def _age(self, client_id, seconds):
        with get_db() as db:
            db.query(McpOAuthClient).filter_by(client_id=client_id).update(
                {"created_at": int(time.time()) - seconds}
            )
            db.commit()

    def test_a_client_without_live_tokens_is_deleted_after_thirty_days(self):
        self.assertEqual(IDLE_CLIENT_SECONDS, 30 * 24 * 60 * 60)
        client_id = self.flow.registered_client_id()
        token(ACCESS, client_id, expires_in=-1)
        self._age(client_id, IDLE_CLIENT_SECONDS + 1)
        purge_once()
        self.assertIsNone(McpOAuth.get_client(client_id))

    def test_a_younger_client_is_kept(self):
        client_id = self.flow.registered_client_id()
        self._age(client_id, IDLE_CLIENT_SECONDS - 60)
        purge_once()
        self.assertIsNotNone(McpOAuth.get_client(client_id))

    def test_an_old_client_with_a_live_token_is_kept(self):
        client_id = self.flow.registered_client_id()
        token(REFRESH, client_id, expires_in=600)
        self._age(client_id, IDLE_CLIENT_SECONDS + 1)
        purge_once()
        self.assertIsNotNone(McpOAuth.get_client(client_id))

    def test_an_old_client_with_only_a_live_code_is_kept(self):
        client_id = self.flow.registered_client_id()
        code(client_id, expires_in=600)
        self._age(client_id, IDLE_CLIENT_SECONDS + 1)
        purge_once()
        self.assertIsNotNone(McpOAuth.get_client(client_id))

    def test_an_old_client_with_a_pending_request_is_kept(self):
        client_id = self.flow.registered_client_id()
        pending(client_id, expires_in=600)
        self._age(client_id, IDLE_CLIENT_SECONDS + 1)
        purge_once()
        self.assertIsNotNone(McpOAuth.get_client(client_id))


class PurgeLoopTest(unittest.TestCase):
    def test_a_failed_run_is_logged_and_the_loop_runs_again(self):
        calls = []

        def purge():
            calls.append(len(calls))
            if len(calls) == 1:
                raise RuntimeError("database unavailable")
            return {}

        async def run():
            task = asyncio.create_task(retention.purge_forever(interval=0))
            while len(calls) < 2:
                await asyncio.sleep(0.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        with patch.object(retention, "purge_once", purge), self.assertLogs(
            "open_webui.mcp_oauth.retention", level="ERROR"
        ) as logged:
            asyncio.run(asyncio.wait_for(run(), timeout=10))
        self.assertGreaterEqual(len(calls), 2)
        self.assertEqual(len([r for r in logged.records if r.exc_info]), 1)


class RateLimitTest(EndpointCase):
    def test_register_answers_429_over_the_limit(self):
        for _ in range(REGISTER_LIMIT):
            self.assertEqual(self.flow.register().status_code, 201)
        response = self.flow.register()
        self.assertEqual(response.status_code, 429)
        self.assertIn("retry-after", response.headers)

    def test_authorize_answers_429_over_the_limit(self):
        client_id = self.flow.registered_client_id()
        for _ in range(AUTHORIZE_LIMIT):
            self.assertEqual(self.flow.authorize(client_id).status_code, 302)
        self.assertEqual(self.flow.authorize(client_id).status_code, 429)

    def test_a_preflight_is_not_counted(self):
        for _ in range(REGISTER_LIMIT + 1):
            self.client.options(
                "/register",
                headers={"Origin": "https://a.example", "Access-Control-Request-Method": "POST"},
            )
        self.assertEqual(self.flow.register().status_code, 201)

    def test_the_count_starts_again_in_the_next_window(self):
        now = [1_000_000.0]
        self.provider.rate_limiter.clock = lambda: now[0]
        for _ in range(REGISTER_LIMIT):
            self.flow.register()
        self.assertEqual(self.flow.register().status_code, 429)
        now[0] += self.provider.rate_limiter.window_seconds
        self.assertEqual(self.flow.register().status_code, 201)

    def test_retry_after_is_the_time_left_in_the_window(self):
        now = [1_000_020.0]
        self.provider.rate_limiter.clock = lambda: now[0]
        window = self.provider.rate_limiter.window_seconds
        for _ in range(REGISTER_LIMIT):
            self.flow.register()
        response = self.flow.register()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], str(window - int(now[0]) % window))


class FakeRedis:
    """Records a MULTI/EXEC pipeline of SET NX EX and INCR, as redis-py runs it."""

    def __init__(self):
        self.values = {}
        self.expiries = {}
        self.transactions = []

    def pipeline(self, transaction=True):
        return FakePipeline(self, transaction)


class FakePipeline:
    def __init__(self, redis, transaction):
        self.redis = redis
        self.transaction = transaction
        self.commands = []

    def set(self, key, value, ex=None, nx=False):
        self.commands.append(("set", key, value, ex, nx))

    def incr(self, key):
        self.commands.append(("incr", key))

    def execute(self):
        self.redis.transactions.append((self.transaction, [c[0] for c in self.commands]))
        results = []
        for command in self.commands:
            if command[0] == "set":
                _, key, value, ex, nx = command
                if nx and key in self.redis.values:
                    results.append(None)
                    continue
                self.redis.values[key] = value
                self.redis.expiries[key] = ex
                results.append(True)
            else:
                key = command[1]
                self.redis.values[key] = self.redis.values.get(key, 0) + 1
                results.append(self.redis.values[key])
        return results


class RedisCounterTest(unittest.TestCase):
    def test_counts_are_kept_in_redis_with_an_expiry_set_in_the_same_transaction(self):
        redis = FakeRedis()
        limiter = RateLimiter(redis_client=redis, clock=lambda: 120.0)
        self.assertEqual(limiter.hit("register", "203.0.113.5"), 1)
        self.assertEqual(limiter.hit("register", "203.0.113.5"), 2)
        (key,) = redis.values
        self.assertIn("register:203.0.113.5", key)
        self.assertEqual(redis.expiries[key], limiter.window_seconds)
        self.assertEqual(redis.transactions, [(True, ["set", "incr"])] * 2)

    def test_two_limiters_on_one_redis_share_the_count(self):
        # Replicas share the Redis counter.
        redis = FakeRedis()
        first = RateLimiter(redis_client=redis, clock=lambda: 120.0)
        second = RateLimiter(redis_client=redis, clock=lambda: 120.0)
        first.hit("authorize", "203.0.113.5")
        self.assertEqual(second.hit("authorize", "203.0.113.5"), 2)

    def test_a_failing_redis_falls_back_to_the_process_counter(self):
        class Broken:
            def pipeline(self, transaction=True):
                raise ConnectionError("down")

        limiter = RateLimiter(redis_client=Broken(), clock=lambda: 120.0)
        with self.assertLogs("open_webui.mcp_oauth.limits", level="WARNING"):
            self.assertEqual(limiter.hit("register", "203.0.113.5"), 1)

    def test_an_outage_is_logged_once_when_it_starts_and_once_when_it_ends(self):
        healthy = FakeRedis()
        state = {"down": True}

        class Flaky:
            def pipeline(self, transaction=True):
                if state["down"]:
                    raise ConnectionError("down")
                return healthy.pipeline(transaction)

        limiter = RateLimiter(redis_client=Flaky(), clock=lambda: 120.0)
        with self.assertLogs("open_webui.mcp_oauth.limits", level="WARNING") as logged:
            for _ in range(5):
                limiter.hit("register", "203.0.113.5")
            state["down"] = False
            for _ in range(3):
                limiter.hit("register", "203.0.113.5")
        messages = [record.getMessage() for record in logged.records]
        self.assertEqual(len(messages), 2, messages)
        self.assertIn("failed", messages[0])
        self.assertIn("answers again", messages[1])

    def test_without_redis_url_the_process_counter_is_used(self):
        with patch("open_webui.mcp_oauth.limits.REDIS_URL", ""):
            from open_webui.mcp_oauth.limits import redis_client_from_env

            self.assertIsNone(redis_client_from_env())


class LocalCounterCapTest(unittest.TestCase):
    def test_the_oldest_counter_is_evicted_when_the_window_is_full(self):
        limiter = RateLimiter(clock=lambda: 120.0)
        with patch("open_webui.mcp_oauth.limits.MAX_LOCAL_COUNTERS", 3):
            for n in range(3):
                self.assertEqual(limiter.hit("register", f"203.0.113.{n}"), 1)
            limiter.hit("register", "203.0.113.1")
            # A new address is counted, and the oldest counter makes room for it.
            self.assertEqual(limiter.hit("register", "203.0.113.9"), 1)
            self.assertEqual(len(limiter._counts), 3)
            self.assertEqual(limiter.hit("register", "203.0.113.1"), 3)
            self.assertEqual(limiter.hit("register", "203.0.113.0"), 1)

    def test_past_windows_are_dropped_to_make_room(self):
        now = [120.0]
        limiter = RateLimiter(clock=lambda: now[0])
        with patch("open_webui.mcp_oauth.limits.MAX_LOCAL_COUNTERS", 3):
            for n in range(3):
                limiter.hit("register", f"203.0.113.{n}")
            now[0] += limiter.window_seconds
            self.assertEqual(limiter.hit("register", "203.0.113.9"), 1)
            self.assertEqual(len(limiter._counts), 1)


if __name__ == "__main__":
    unittest.main()
