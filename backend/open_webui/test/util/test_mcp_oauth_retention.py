"""Deleting unusable authorization rows."""

import io
import logging
import runpy
import secrets
import time
import unittest
import uuid
from contextlib import redirect_stdout
from unittest.mock import patch

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


class CommandTest(EndpointCase):
    def test_a_run_deletes_unusable_rows_logs_them_and_exits_zero(self):
        client_id = self.flow.registered_client_id()
        expired = token(ACCESS, client_id, expires_in=-1)
        with self.assertLogs("open_webui.mcp_oauth.retention", level="INFO") as logged:
            self.assertEqual(retention.main(), 0)
        self.assertFalse(row_exists(McpOAuthToken, token_hash=digest(expired)))
        self.assertEqual(len(logged.records), 1)
        self.assertGreaterEqual(logged.records[0].args["tokens"], 1)

    def test_a_run_with_nothing_to_delete_logs_zero_counts(self):
        purge_once()
        with self.assertLogs("open_webui.mcp_oauth.retention", level="INFO") as logged:
            self.assertEqual(retention.main(), 0)
        self.assertEqual(len(logged.records), 1)
        self.assertEqual(logged.records[0].levelno, logging.INFO)
        self.assertFalse(any(logged.records[0].args.values()))

    def test_a_failed_run_is_logged_and_exits_one(self):
        def purge():
            raise RuntimeError("database unavailable")

        with patch.object(retention, "purge_once", purge), self.assertLogs(
            "open_webui.mcp_oauth.retention", level="ERROR"
        ) as logged:
            self.assertEqual(retention.main(), 1)
        self.assertEqual(len([r for r in logged.records if r.exc_info]), 1)

    def _run_as_script(self):
        """Run the module as `python -m` does. Returns the exit code and what reached stdout."""
        logger = logging.getLogger("open_webui.mcp_oauth.retention")
        self.addCleanup(logger.setLevel, logger.level)
        self.addCleanup(logging.root.setLevel, logging.root.level)
        stdout = io.StringIO()
        # pytest puts its capture handlers on the root logger, which would make the script's
        # basicConfig a no-op. An empty handler list lets it add its stdout handler for this run.
        with patch.object(logging.root, "handlers", []), redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as exited:
                runpy.run_module("open_webui.mcp_oauth.retention", run_name="__main__")
        return exited.exception.code, stdout.getvalue()

    def test_the_script_exits_zero_and_prints_the_summary(self):
        code, output = self._run_as_script()
        self.assertEqual(code, 0)
        self.assertIn("MCP OAuth retention deleted", output)

    def test_the_script_exits_one_when_the_run_fails(self):
        # runpy executes a fresh copy of the module, so the store it calls is patched instead of
        # its purge_once.
        with patch.object(McpOAuth, "purge", side_effect=RuntimeError("database unavailable")):
            code, output = self._run_as_script()
        self.assertEqual(code, 1)
        self.assertIn("MCP OAuth retention run failed", output)


if __name__ == "__main__":
    unittest.main()
