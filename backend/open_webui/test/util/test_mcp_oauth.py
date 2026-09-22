"""The built-in authorization server, through the host application, against the database.

Accounts are real rows in the application's database. The interface session is the `token` cookie
its sign-in sets. The classes cover the full flow, sign-in and consent, code and refresh reuse,
expiry and revocation, the resource indicator, registration, and the redirect-URI policy.
"""

import asyncio
import base64
import hashlib
import json
import re
import secrets
import threading
import time
import unittest
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from mcp.server.auth.provider import RegistrationError, TokenError
from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE
from mcp.shared.auth import OAuthClientInformationFull

from open_webui.mcp import SERVED_PATH, build_endpoint
from open_webui.mcp import tools as endpoint_tools
from open_webui.mcp.auth import MCP_PATH
from open_webui.mcp_oauth.provider import (
    ACCESS_LIFETIME_SECONDS,
    CONSENT_PATH,
    REFRESH_REUSE_GRACE_SECONDS,
    EndpointOAuthProvider,
    _same_loopback_redirect,
    consent_request_path,
    redirect_uri_allowed,
)
from open_webui.internal.db import get_db
from open_webui.models.mcp_oauth import ACCESS, REFRESH, McpOAuth, McpOAuthToken, digest
from open_webui.models.users import Users
from open_webui.test.util.mcp_host import (
    SERVICE_URL,
    host_application,
    service_configured,
)
from open_webui.utils.auth import create_token

IDENTIFIER = f"{SERVICE_URL}{MCP_PATH}"
REDIRECT_URI = "http://127.0.0.1:33418/callback"
CLIENT_NAME = "A test client"
TOOL_NAME = "who_am_i"

FORM_FIELD = re.compile(r'name="(request|form)" value="([^"]*)"')

INITIALIZE_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2026-07-28",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def new_account(role="user"):
    user_id = str(uuid.uuid4())
    Users.insert_new_user(user_id, "Test user", f"{user_id}@example.com", role=role)
    return user_id


@contextmanager
def after_refresh_grace():
    """Run with the clock past the refresh-reuse grace window of a token rotated just now."""
    later = time.time() + REFRESH_REUSE_GRACE_SECONDS + 1
    with patch("time.time", return_value=later):
        yield


def session_cookie(user_id):
    return create_token({"id": user_id})


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def query(location):
    return {key: values[0] for key, values in parse_qs(urlsplit(location).query).items()}


def rpc_result(response):
    """The JSON-RPC message in a Streamable HTTP response, which may be an SSE stream."""
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data = [
            line[len("data:") :].strip()
            for line in response.text.splitlines()
            if line.startswith("data:")
        ]
        return json.loads(data[-1])
    return response.json()


class Flow:
    """Drives the authorization flow through the host application's test client."""

    def __init__(self, case, client):
        self.case = case
        self.client = client
        self.verifier, self.challenge = pkce_pair()

    def register(self, redirect_uris=(REDIRECT_URI,), method="none"):
        response = self.client.post(
            "/register",
            json={
                "redirect_uris": list(redirect_uris),
                "token_endpoint_auth_method": method,
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_name": CLIENT_NAME,
            },
        )
        return response

    def registered_client_id(self):
        response = self.register()
        self.case.assertEqual(response.status_code, 201, response.text)
        return response.json()["client_id"]

    def authorize(self, client_id, redirect_uri=REDIRECT_URI, resource=IDENTIFIER, state="st"):
        """GET /authorize. redirect_uri=None or resource=None omits that parameter."""
        params = {
            "response_type": "code",
            "client_id": client_id,
            "code_challenge": self.challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
        if redirect_uri is not None:
            params["redirect_uri"] = redirect_uri
        if resource is not None:
            params["resource"] = resource
        return self.client.get("/authorize", params=params)

    def consent_request(self, client_id, **kwargs):
        response = self.authorize(client_id, **kwargs)
        self.case.assertEqual(response.status_code, 302, response.text)
        location = response.headers["location"]
        self.case.assertTrue(location.startswith(f"{SERVICE_URL}{CONSENT_PATH}?"), location)
        return query(location)["request"]

    def signed_in(self, user_id):
        self.client.cookies.clear()
        if user_id is not None:
            self.client.cookies.set("token", session_cookie(user_id))

    def consent_page(self, request_id):
        return self.client.get(CONSENT_PATH, params={"request": request_id})

    def form_fields(self, page):
        fields = dict(FORM_FIELD.findall(page.text))
        self.case.assertIn("form", fields, page.text)
        return fields

    def decide(self, fields, decision):
        return self.client.post(CONSENT_PATH, data={**fields, "decision": decision})

    def approved_location(self, client_id, user_id, **kwargs):
        request_id = self.consent_request(client_id, **kwargs)
        self.signed_in(user_id)
        page = self.consent_page(request_id)
        self.case.assertEqual(page.status_code, 200, page.text)
        response = self.decide(self.form_fields(page), "approve")
        self.case.assertEqual(response.status_code, 303, response.text)
        return response.headers["location"]

    def code(self, client_id, user_id, **kwargs):
        return query(self.approved_location(client_id, user_id, **kwargs))["code"]

    def exchange(self, client_id, code, redirect_uri=REDIRECT_URI):
        """POST /token for a code. redirect_uri=None omits that parameter."""
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "code_verifier": self.verifier,
        }
        if redirect_uri is not None:
            data["redirect_uri"] = redirect_uri
        return self.client.post("/token", data=data)

    def tokens(self, client_id, user_id):
        response = self.exchange(client_id, self.code(client_id, user_id))
        self.case.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def refresh(self, client_id, refresh_token):
        return self.client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
        )

    def revoke(self, client_id, value):
        return self.client.post("/revoke", data={"token": value, "client_id": client_id})

    def mcp_initialize(self, access_token):
        return self.client.post(
            SERVED_PATH,
            json=INITIALIZE_REQUEST,
            headers={**MCP_HEADERS, "Authorization": f"Bearer {access_token}"},
        )

    def call_tool(self, access_token):
        """Initialize a session and call TOOL_NAME. Returns the tools/call result message."""
        auth = {**MCP_HEADERS, "Authorization": f"Bearer {access_token}"}
        started = self.mcp_initialize(access_token)
        self.case.assertEqual(started.status_code, 200, started.text)
        negotiated = rpc_result(started)["result"]["protocolVersion"]
        session = {"mcp-protocol-version": negotiated}
        if "mcp-session-id" in started.headers:
            session["mcp-session-id"] = started.headers["mcp-session-id"]
        self.client.post(
            SERVED_PATH,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            headers={**auth, **session},
        )
        called = self.client.post(
            SERVED_PATH,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": TOOL_NAME, "arguments": {}},
            },
            headers={**auth, **session},
        )
        self.case.assertEqual(called.status_code, 200, called.text)
        return rpc_result(called)


def catalog_for(app, account, organization_id, context):
    """A catalog whose one tool reports the id of the account it runs as."""

    async def who_am_i(**arguments):
        return {"ok": True, "stdout": account.id}

    return {
        TOOL_NAME: {
            "spec": {
                "name": TOOL_NAME,
                "description": "Reports the caller.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
            "callable": who_am_i,
        }
    }


class EndpointCase(unittest.TestCase):
    """Builds the endpoint and a host application client for each test."""

    def setUp(self):
        with service_configured():
            self.endpoint = build_endpoint(SimpleNamespace(state=SimpleNamespace(TOOLS={})))
        self.assertIsNotNone(self.endpoint)
        self.provider = self.endpoint.provider
        self.assertIsInstance(self.provider, EndpointOAuthProvider)
        self.host = host_application(self.endpoint, follow_redirects=False)
        self.client = self.host.__enter__()
        self.addCleanup(self.host.__exit__, None, None, None)
        self.flow = Flow(self, self.client)


class FullFlowTest(EndpointCase):
    def setUp(self):
        super().setUp()
        for started in (
            patch.object(endpoint_tools, "call_organization_id", return_value="an-org"),
            patch.object(endpoint_tools, "endpoint_catalog", side_effect=catalog_for),
            patch.object(
                endpoint_tools, "owned_session", return_value=SimpleNamespace(id="a-session")
            ),
            patch.object(endpoint_tools, "record_tool_call"),
            patch.object(endpoint_tools, "run_context", return_value={}),
            patch.object(endpoint_tools, "caller_only_context", return_value={}),
        ):
            started.start()
            self.addCleanup(started.stop)

    def test_the_code_exchange_returns_an_access_and_a_refresh_token(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        self.assertTrue(tokens["access_token"])
        self.assertTrue(tokens["refresh_token"])
        self.assertEqual(tokens["token_type"], "Bearer")
        self.assertEqual(tokens["expires_in"], ACCESS_LIFETIME_SECONDS)

    def test_a_tool_call_runs_as_the_approving_user(self):
        user_id = new_account()
        client_id = self.flow.registered_client_id()
        access = self.flow.tokens(client_id, user_id)["access_token"]
        result = self.flow.call_tool(access)
        self.assertNotIn("error", result, result)
        self.assertIn(user_id, json.dumps(result["result"]))

    def test_only_digests_are_stored(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        # The raw value finds the row only through its digest.
        record = McpOAuth.get_token(tokens["access_token"], ACCESS)
        self.assertEqual(
            record.token_hash, hashlib.sha256(tokens["access_token"].encode()).hexdigest()
        )
        self.assertNotEqual(record.token_hash, tokens["access_token"])

    def test_the_access_token_carries_the_resource_identifier(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        self.assertEqual(McpOAuth.get_token(tokens["access_token"], ACCESS).resource, IDENTIFIER)


class NotSignedInTest(EndpointCase):
    def test_the_consent_page_sends_the_user_to_sign_in(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(None)
        response = self.flow.consent_page(request_id)
        self.assertEqual(response.status_code, 302)
        location = response.headers["location"]
        self.assertTrue(location.startswith(f"{SERVICE_URL}/auth?redirect="), location)

    def test_the_sign_in_redirect_is_a_path_back_to_the_consent_page(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(None)
        location = self.flow.consent_page(request_id).headers["location"]
        # query() decodes the value once, as the sign-in page's URLSearchParams does.
        back = query(location)["redirect"]
        self.assertEqual(back, consent_request_path(request_id))
        self.assertNotIn("://", back)

    def test_after_sign_in_the_same_path_shows_the_approval(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(None)
        back = query(self.flow.consent_page(request_id).headers["location"])["redirect"]
        self.assertEqual(back, consent_request_path(request_id))
        self.flow.signed_in(new_account())
        page = self.client.get(back)
        self.assertEqual(page.status_code, 200)
        self.assertIn(CLIENT_NAME, page.text)
        self.assertIn("127.0.0.1:33418", page.text)


class PendingAccountTest(EndpointCase):
    def test_no_consent_page_and_no_redirect_to_the_client(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(new_account(role="pending"))
        response = self.flow.consent_page(request_id)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("location", response.headers)
        self.assertIn("pending", response.text)

    def test_an_approval_from_a_pending_account_issues_no_code(self):
        # The form was shown while the account was active; it was demoted before approving.
        user_id = new_account()
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(user_id)
        fields = self.flow.form_fields(self.flow.consent_page(request_id))
        Users.update_user_role_by_id(user_id, "pending")
        response = self.flow.decide(fields, "approve")
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("location", response.headers)


class CodeReplayTest(EndpointCase):
    def test_a_second_exchange_of_the_same_code_is_refused(self):
        client_id = self.flow.registered_client_id()
        code = self.flow.code(client_id, new_account())
        first = self.flow.exchange(client_id, code)
        second = self.flow.exchange(client_id, code)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(second.json()["error"], "invalid_grant")

    def test_a_replayed_code_revokes_the_tokens_issued_for_it(self):
        # Immediately, with no grace window as refresh tokens have.
        client_id = self.flow.registered_client_id()
        code = self.flow.code(client_id, new_account())
        tokens = self.flow.exchange(client_id, code).json()
        self.assertEqual(self.flow.mcp_initialize(tokens["access_token"]).status_code, 200)
        self.assertEqual(self.flow.exchange(client_id, code).json()["error"], "invalid_grant")
        self.assertEqual(self.flow.mcp_initialize(tokens["access_token"]).status_code, 401)
        self.assertEqual(
            self.flow.refresh(client_id, tokens["refresh_token"]).json()["error"],
            "invalid_grant",
        )

    def test_two_concurrent_exchanges_yield_exactly_one_token(self):
        # Two threads, each with its own event loop and database session, exchange one code
        # against the shared database at the same moment.
        client_id = self.flow.registered_client_id()
        code = self.flow.code(client_id, new_account())
        client = asyncio.run(self.provider.get_client(client_id))
        loaded = asyncio.run(self.provider.load_authorization_code(client, code))
        barrier = threading.Barrier(2)
        outcomes = []

        def exchange():
            barrier.wait()
            try:
                outcomes.append(
                    asyncio.run(self.provider.exchange_authorization_code(client, loaded))
                )
            except TokenError as error:
                outcomes.append(error)

        threads = [threading.Thread(target=exchange) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        issued = [outcome for outcome in outcomes if not isinstance(outcome, TokenError)]
        refused = [outcome for outcome in outcomes if isinstance(outcome, TokenError)]
        self.assertEqual(len(issued), 1, outcomes)
        self.assertEqual(len(refused), 1, outcomes)
        self.assertEqual(refused[0].error, "invalid_grant")


class ExpiryTest(EndpointCase):
    def test_an_expired_code_is_refused(self):
        user_id = new_account()
        client_id = self.flow.registered_client_id()
        code = secrets.token_urlsafe(32)
        McpOAuth.insert_code(
            code,
            client_id=client_id,
            user_id=user_id,
            redirect_uri=REDIRECT_URI,
            redirect_uri_provided_explicitly=True,
            code_challenge=self.flow.challenge,
            scopes=[],
            resource=IDENTIFIER,
            expires_at=int(time.time()) - 1,
        )
        response = self.flow.exchange(client_id, code)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_a_code_is_refused_ten_minutes_after_it_was_issued(self):
        client_id = self.flow.registered_client_id()
        issued_at = time.time()
        code = self.flow.code(client_id, new_account())
        later = issued_at + 10 * 60 + 1
        with patch("time.time", return_value=later):
            response = self.flow.exchange(client_id, code)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_an_access_token_gets_401_an_hour_after_it_was_issued(self):
        client_id = self.flow.registered_client_id()
        issued_at = time.time()
        access = self.flow.tokens(client_id, new_account())["access_token"]
        later = issued_at + 60 * 60 + 1
        with patch("time.time", return_value=later):
            self.assertEqual(self.flow.mcp_initialize(access).status_code, 401)

    def test_an_expired_pending_request_is_refused(self):
        client_id = self.flow.registered_client_id()
        request_id = secrets.token_urlsafe(32)
        McpOAuth.insert_authorization(
            request_id,
            client_id=client_id,
            redirect_uri=REDIRECT_URI,
            redirect_uri_provided_explicitly=True,
            state="st",
            code_challenge=self.flow.challenge,
            scopes=[],
            resource=IDENTIFIER,
            expires_at=int(time.time()) - 1,
        )
        self.flow.signed_in(new_account())
        self.assertEqual(self.flow.consent_page(request_id).status_code, 400)
        response = self.flow.decide(
            {"request": request_id, "form": secrets.token_urlsafe(32)}, "approve"
        )
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("location", response.headers)

    def test_an_expired_access_token_gets_401(self):
        access = secrets.token_urlsafe(32)
        McpOAuth.insert_token(
            access,
            kind=ACCESS,
            grant_id=str(uuid.uuid4()),
            client_id="a-client",
            user_id=new_account(),
            scopes=[],
            resource=IDENTIFIER,
            expires_at=int(time.time()) - 1,
        )
        self.assertEqual(self.flow.mcp_initialize(access).status_code, 401)

    def test_a_revoked_access_token_gets_401(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        self.assertEqual(self.flow.mcp_initialize(tokens["access_token"]).status_code, 200)
        self.assertEqual(self.flow.revoke(client_id, tokens["access_token"]).status_code, 200)
        self.assertEqual(self.flow.mcp_initialize(tokens["access_token"]).status_code, 401)

    def test_revoking_the_refresh_token_revokes_its_access_token(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        self.flow.revoke(client_id, tokens["refresh_token"])
        self.assertEqual(self.flow.mcp_initialize(tokens["access_token"]).status_code, 401)
        self.assertEqual(
            self.flow.refresh(client_id, tokens["refresh_token"]).json()["error"],
            "invalid_grant",
        )

    def test_another_client_cannot_revoke_a_token(self):
        client_id = self.flow.registered_client_id()
        other_client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        self.assertEqual(self.flow.revoke(other_client_id, tokens["access_token"]).status_code, 200)
        self.assertEqual(self.flow.mcp_initialize(tokens["access_token"]).status_code, 200)

    def test_a_code_approved_before_demotion_is_refused(self):
        user_id = new_account()
        client_id = self.flow.registered_client_id()
        code = self.flow.code(client_id, user_id)
        Users.update_user_role_by_id(user_id, "pending")
        self.assertEqual(self.flow.exchange(client_id, code).json()["error"], "invalid_grant")

    def test_a_refresh_after_demotion_is_refused(self):
        user_id = new_account()
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, user_id)
        Users.update_user_role_by_id(user_id, "pending")
        response = self.flow.refresh(client_id, tokens["refresh_token"])
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_a_demoted_account_gets_401(self):
        # The role is read on every request, not only when the token was issued.
        user_id = new_account()
        client_id = self.flow.registered_client_id()
        access = self.flow.tokens(client_id, user_id)["access_token"]
        Users.update_user_role_by_id(user_id, "pending")
        self.assertEqual(self.flow.mcp_initialize(access).status_code, 401)


class RefreshReuseTest(EndpointCase):
    def test_a_refresh_rotates_the_refresh_token(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        refreshed = self.flow.refresh(client_id, tokens["refresh_token"])
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertNotEqual(refreshed.json()["refresh_token"], tokens["refresh_token"])
        self.assertEqual(
            self.flow.mcp_initialize(refreshed.json()["access_token"]).status_code, 200
        )

    def test_the_rotated_refresh_token_is_refused_after_the_grace_window(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        self.flow.refresh(client_id, tokens["refresh_token"])
        with after_refresh_grace():
            again = self.flow.refresh(client_id, tokens["refresh_token"])
        self.assertEqual(again.json()["error"], "invalid_grant")

    def test_reusing_a_rotated_refresh_token_after_the_grace_window_revokes_the_grant(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        rotated = self.flow.refresh(client_id, tokens["refresh_token"]).json()
        self.assertEqual(self.flow.mcp_initialize(rotated["access_token"]).status_code, 200)
        with after_refresh_grace():
            self.flow.refresh(client_id, tokens["refresh_token"])
            self.assertEqual(self.flow.mcp_initialize(rotated["access_token"]).status_code, 401)
            self.assertEqual(
                self.flow.refresh(client_id, rotated["refresh_token"]).json()["error"],
                "invalid_grant",
            )

    def _live_refresh_tokens(self, value):
        """Live refresh tokens in the grant of the token `value`."""
        with get_db() as db:
            grant_id = db.query(McpOAuthToken).filter_by(token_hash=digest(value)).one().grant_id
            return (
                db.query(McpOAuthToken)
                .filter(
                    McpOAuthToken.grant_id == grant_id,
                    McpOAuthToken.kind == REFRESH,
                    McpOAuthToken.revoked_at.is_(None),
                )
                .count()
            )

    def test_a_retry_within_the_grace_window_gets_a_new_pair_and_keeps_the_grant(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        first = self.flow.refresh(client_id, tokens["refresh_token"]).json()
        retried = self.flow.refresh(client_id, tokens["refresh_token"])
        self.assertEqual(retried.status_code, 200, retried.text)
        second = retried.json()
        self.assertNotEqual(second["refresh_token"], first["refresh_token"])
        self.assertEqual(self.flow.mcp_initialize(second["access_token"]).status_code, 200)
        self.assertEqual(self.flow.refresh(client_id, second["refresh_token"]).status_code, 200)

    def test_a_grace_retry_replaces_the_first_successor(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        first = self.flow.refresh(client_id, tokens["refresh_token"]).json()
        second = self.flow.refresh(client_id, tokens["refresh_token"]).json()
        self.assertEqual(self.flow.mcp_initialize(second["access_token"]).status_code, 200)
        self.assertEqual(self.flow.mcp_initialize(first["access_token"]).status_code, 401)

    def test_a_raced_client_can_refresh_with_its_replaced_successor_within_the_window(self):
        # Two refreshes of R1 (the second handled as a grace retry) give R2 and R3. The client
        # that kept R2 refreshes with it inside the window.
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        r2 = self.flow.refresh(client_id, tokens["refresh_token"]).json()
        r3 = self.flow.refresh(client_id, tokens["refresh_token"]).json()
        response = self.flow.refresh(client_id, r2["refresh_token"])
        self.assertEqual(response.status_code, 200, response.text)
        latest = response.json()
        self.assertEqual(self._live_refresh_tokens(tokens["refresh_token"]), 1)
        self.assertEqual(self.flow.mcp_initialize(latest["access_token"]).status_code, 200)
        self.assertEqual(self.flow.mcp_initialize(r3["access_token"]).status_code, 401)
        self.assertEqual(self.flow.refresh(client_id, latest["refresh_token"]).status_code, 200)

    def test_a_replaced_successor_after_the_window_is_reuse(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        r2 = self.flow.refresh(client_id, tokens["refresh_token"]).json()
        r3 = self.flow.refresh(client_id, tokens["refresh_token"]).json()
        with after_refresh_grace():
            refused = self.flow.refresh(client_id, r2["refresh_token"])
            self.assertEqual(refused.json()["error"], "invalid_grant")
            self.assertEqual(self.flow.mcp_initialize(r3["access_token"]).status_code, 401)

    def test_repeated_grace_retries_leave_one_live_refresh_token(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        self.flow.refresh(client_id, tokens["refresh_token"])
        self.flow.refresh(client_id, tokens["refresh_token"])
        third = self.flow.refresh(client_id, tokens["refresh_token"])
        self.assertEqual(third.status_code, 200, third.text)
        self.assertEqual(self._live_refresh_tokens(tokens["refresh_token"]), 1)

    def test_no_grace_after_the_grant_was_revoked(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        rotated = self.flow.refresh(client_id, tokens["refresh_token"]).json()
        self.flow.revoke(client_id, rotated["refresh_token"])
        again = self.flow.refresh(client_id, tokens["refresh_token"])
        self.assertEqual(again.json()["error"], "invalid_grant")
        self.assertEqual(self._live_refresh_tokens(tokens["refresh_token"]), 0)

    def test_the_grace_window_is_thirty_seconds(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        rotated_at = time.time()
        self.flow.refresh(client_id, tokens["refresh_token"])
        with patch("time.time", return_value=rotated_at + 29):
            inside = self.flow.refresh(client_id, tokens["refresh_token"])
        self.assertEqual(inside.status_code, 200, inside.text)
        with patch("time.time", return_value=rotated_at + 32):
            outside = self.flow.refresh(client_id, tokens["refresh_token"])
        self.assertEqual(outside.json()["error"], "invalid_grant")


class WrongAudienceTest(EndpointCase):
    def test_a_token_for_another_resource_gets_401(self):
        access = secrets.token_urlsafe(32)
        McpOAuth.insert_token(
            access,
            kind=ACCESS,
            grant_id=str(uuid.uuid4()),
            client_id="a-client",
            user_id=new_account(),
            scopes=[],
            resource="https://other.example/mcp",
            expires_at=int(time.time()) + 600,
        )
        self.assertEqual(self.flow.mcp_initialize(access).status_code, 401)

    def test_an_authorization_request_for_another_resource_is_refused(self):
        client_id = self.flow.registered_client_id()
        response = self.flow.authorize(client_id, resource="https://other.example/mcp")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(query(response.headers["location"])["error"], "invalid_target")

    def test_a_request_without_a_resource_gets_a_token_for_this_endpoint(self):
        client_id = self.flow.registered_client_id()
        # approved_location asserts the redirect to the consent page.
        location = self.flow.approved_location(client_id, new_account(), resource=None)
        access = self.flow.exchange(client_id, query(location)["code"]).json()["access_token"]
        self.assertEqual(McpOAuth.get_token(access, ACCESS).resource, IDENTIFIER)
        self.assertEqual(self.flow.mcp_initialize(access).status_code, 200)

    def test_a_trailing_slash_on_the_resource_is_the_same_resource(self):
        client_id = self.flow.registered_client_id()
        location = self.flow.approved_location(
            client_id, new_account(), resource=f"{IDENTIFIER}/"
        )
        access = self.flow.exchange(client_id, query(location)["code"]).json()["access_token"]
        self.assertEqual(McpOAuth.get_token(access, ACCESS).resource, IDENTIFIER)
        self.assertEqual(self.flow.mcp_initialize(access).status_code, 200)


class RegistrationCollisionTest(EndpointCase):
    def test_an_existing_client_is_never_replaced(self):
        client_id = self.flow.registered_client_id()
        before = McpOAuth.get_client(client_id)
        replacement = OAuthClientInformationFull(
            client_id=client_id,
            redirect_uris=["http://localhost:1/other"],
            token_endpoint_auth_method="none",
            client_name="Someone else",
        )
        with self.assertRaises(RegistrationError):
            asyncio.run(self.provider.register_client(replacement))
        self.assertEqual(McpOAuth.get_client(client_id), before)


class DisallowedRedirectTest(EndpointCase):
    def test_registration_with_a_remote_redirect_is_refused(self):
        response = self.flow.register(redirect_uris=["https://elsewhere.example/callback"])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "invalid_redirect_uri")

    def test_an_allowlisted_redirect_registers(self):
        self.provider.allowed_redirect_uris = ("https://test-host.example/callback",)
        response = self.flow.register(redirect_uris=["https://test-host.example/callback"])
        self.assertEqual(response.status_code, 201, response.text)


class RedirectPolicyTest(unittest.TestCase):
    ALLOWED = (
        "https://exact.example/callback",
        "https://prefix.example/oauth/*",
        "http://test-host.internal:8080/cb",
    )

    def allowed(self, uri):
        return redirect_uri_allowed(uri, self.ALLOWED)

    def test_loopback_http_on_any_port(self):
        for uri in (
            "http://localhost:1/callback",
            "http://127.0.0.1:65000/cb",
            "http://[::1]:4000/cb",
            "http://localhost/callback",
        ):
            self.assertTrue(self.allowed(uri), uri)

    def test_an_exact_entry(self):
        self.assertTrue(self.allowed("https://exact.example/callback"))
        self.assertFalse(self.allowed("https://exact.example/callback/more"))

    def test_a_prefix_entry(self):
        self.assertTrue(self.allowed("https://prefix.example/oauth/callback"))
        self.assertFalse(self.allowed("https://prefix.example/other"))

    def test_any_scheme_may_be_listed(self):
        self.assertTrue(self.allowed("http://test-host.internal:8080/cb"))

    def test_others_are_refused(self):
        for uri in (
            "https://elsewhere.example/callback",
            "https://localhost/callback",
            "http://localhost.elsewhere.example/cb",
        ):
            self.assertFalse(self.allowed(uri), uri)

    def test_user_info_cannot_satisfy_a_prefix(self):
        self.assertFalse(
            redirect_uri_allowed("https://prefix.example@evil.example/", ["https://prefix.example*"])
        )
        self.assertFalse(self.allowed("http://localhost@evil.example/cb"))

    def test_dot_segments_cannot_escape_a_prefix(self):
        self.assertFalse(self.allowed("https://prefix.example/oauth/../steal"))

    def test_percent_encoded_dot_segments_are_refused(self):
        for uri in (
            "https://prefix.example/oauth/%2e%2e/steal",
            "https://prefix.example/oauth/%2E%2E/steal",
            "https://prefix.example/oauth/.%2e/steal",
            "https://prefix.example/oauth/%252e%252e/steal",
            "http://localhost:1/%2e%2e/cb",
        ):
            self.assertFalse(self.allowed(uri), uri)

    def test_dot_segments_encoded_deeper_than_the_decode_rounds_are_refused(self):
        deep = ".."
        for _ in range(8):
            deep = deep.replace("%", "%25").replace(".", "%2e")
        self.assertFalse(self.allowed(f"https://prefix.example/oauth/{deep}/steal"))
        # A path that decodes a few times and then settles is still allowed.
        self.assertTrue(self.allowed("https://prefix.example/oauth/a%2520b"))

    def test_a_prefix_entry_does_not_extend_its_host(self):
        entry = ["https://app.example*"]
        self.assertTrue(redirect_uri_allowed("https://app.example/cb", entry))
        for uri in (
            "https://app.example.evil.com/cb",
            "https://app.exampleevil.com/cb",
            "https://app.example:8443/cb",
            "http://app.example/cb",
        ):
            self.assertFalse(redirect_uri_allowed(uri, entry), uri)

    def test_a_prefix_entry_keeps_its_port(self):
        entry = ["http://test-host.internal:8080/oauth/*"]
        self.assertTrue(redirect_uri_allowed("http://test-host.internal:8080/oauth/cb", entry))
        self.assertFalse(redirect_uri_allowed("http://test-host.internal:8081/oauth/cb", entry))
        self.assertFalse(redirect_uri_allowed("http://test-host.internal/oauth/cb", entry))


class RegisteredLoopbackRedirectTest(EndpointCase):
    """A registered loopback redirect is matched on any port, and nothing else is loosened."""

    def test_a_different_port_on_the_same_host_and_path_is_accepted(self):
        client_id = self.flow.registered_client_id()
        self.flow.consent_request(client_id, redirect_uri="http://127.0.0.1:50001/callback")

    def test_a_different_path_is_refused(self):
        client_id = self.flow.registered_client_id()
        response = self.flow.authorize(client_id, redirect_uri="http://127.0.0.1:33418/other")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("location", response.headers)

    def test_a_different_loopback_host_is_refused(self):
        client_id = self.flow.registered_client_id()
        response = self.flow.authorize(client_id, redirect_uri="http://localhost:33418/callback")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("location", response.headers)

    def test_the_matcher_refuses_dot_segments_instead_of_resolving_them(self):
        # The SDK parses redirect_uri with pydantic, which resolves dot segments before the
        # provider sees it, so this is checked on the matcher directly.
        registered = "http://127.0.0.1:33418/callback"
        self.assertTrue(_same_loopback_redirect("http://127.0.0.1:1/callback", registered))
        for requested in (
            "http://127.0.0.1:1/x/../callback",
            "http://127.0.0.1:1/x/%2e%2e/callback",
            "http://127.0.0.1:1/./callback",
        ):
            self.assertFalse(_same_loopback_redirect(requested, registered), requested)


class NarrowedAllowlistTest(EndpointCase):
    def test_an_existing_registration_is_refused_after_its_entry_is_removed(self):
        remote = "https://test-host.example/callback"
        self.provider.allowed_redirect_uris = (remote,)
        response = self.flow.register(redirect_uris=[remote])
        self.assertEqual(response.status_code, 201, response.text)
        client_id = response.json()["client_id"]
        self.flow.consent_request(client_id, redirect_uri=remote)

        self.provider.allowed_redirect_uris = ()
        refused = self.flow.authorize(client_id, redirect_uri=remote)
        self.assertEqual(refused.status_code, 400)
        self.assertNotIn("location", refused.headers)

    def test_an_approval_is_refused_when_the_entry_is_removed_after_the_page_was_shown(self):
        remote = "https://test-host.example/callback"
        self.provider.allowed_redirect_uris = (remote,)
        client_id = self.flow.register(redirect_uris=[remote]).json()["client_id"]
        request_id = self.flow.consent_request(client_id, redirect_uri=remote)
        self.flow.signed_in(new_account())
        fields = self.flow.form_fields(self.flow.consent_page(request_id))

        self.provider.allowed_redirect_uris = ()
        response = self.flow.decide(fields, "approve")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("location", response.headers)


class RequestBodyLimitTest(EndpointCase):
    """The SDK's request body limit applies to every authorization server route that takes a body."""

    def _oversized(self, path):
        body = b"a=" + b"x" * DEFAULT_MAX_REQUEST_BODY_SIZE
        return self.client.post(
            path, content=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )

    def test_an_oversized_body_is_refused(self):
        for path in ("/authorize", "/token", "/revoke", "/register"):
            with self.subTest(path=path):
                response = self._oversized(path)
                self.assertEqual(response.status_code, 413, response.text)
                self.assertEqual(response.text, "Request body too large")

    def test_a_body_at_the_limit_reaches_the_handler(self):
        client_id = self.flow.registered_client_id()
        body = f"grant_type=refresh_token&client_id={client_id}&refresh_token=unknown".encode()
        # Starlette's form parser also caps each field at 1 MiB, so the padding is split across
        # fields the handler ignores.
        field = 0
        while len(body) < DEFAULT_MAX_REQUEST_BODY_SIZE:
            prefix = f"&pad{field}=".encode()
            room = DEFAULT_MAX_REQUEST_BODY_SIZE - len(body) - len(prefix)
            if room <= 0:
                break
            body += prefix + b"x" * min(512 * 1024, room)
            field += 1
        self.assertLessEqual(len(body), DEFAULT_MAX_REQUEST_BODY_SIZE)
        response = self.client.post(
            "/token", content=body, headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        self.assertNotEqual(response.status_code, 413)
        self.assertEqual(response.json()["error"], "invalid_grant")

    def test_the_flow_still_completes(self):
        client_id = self.flow.registered_client_id()
        tokens = self.flow.tokens(client_id, new_account())
        self.assertEqual(self.flow.refresh(client_id, tokens["refresh_token"]).status_code, 200)
        self.assertEqual(self.flow.revoke(client_id, tokens["access_token"]).status_code, 200)


class OmittedRedirectUriTest(EndpointCase):
    """A client with exactly one registered redirect URI may omit redirect_uri (RFC 6749 §3.1.2.3).

    The code then records redirect_uri_provided_explicitly=False, and the token request must omit
    redirect_uri as well.
    """

    def test_the_flow_completes_without_redirect_uri(self):
        client_id = self.flow.registered_client_id()
        location = self.flow.approved_location(client_id, new_account(), redirect_uri=None)
        self.assertTrue(location.startswith(REDIRECT_URI), location)
        code = query(location)["code"]
        self.assertIs(McpOAuth.get_code(code).redirect_uri_provided_explicitly, False)
        response = self.flow.exchange(client_id, code, redirect_uri=None)
        self.assertEqual(response.status_code, 200, response.text)
        tokens = response.json()
        self.assertTrue(tokens["access_token"])
        self.assertTrue(tokens["refresh_token"])
        self.assertEqual(self.flow.mcp_initialize(tokens["access_token"]).status_code, 200)

    def test_the_single_registered_uri_is_refused_once_the_allowlist_no_longer_lists_it(self):
        remote = "https://test-host.example/callback"
        self.provider.allowed_redirect_uris = (remote,)
        response = self.flow.register(redirect_uris=[remote])
        self.assertEqual(response.status_code, 201, response.text)
        client_id = response.json()["client_id"]
        self.flow.consent_request(client_id, redirect_uri=None)

        self.provider.allowed_redirect_uris = ()
        refused = self.flow.authorize(client_id, redirect_uri=None)
        self.assertEqual(refused.status_code, 400, refused.text)
        self.assertNotIn("location", refused.headers)
        body = refused.json()
        self.assertEqual(body["error"], "invalid_request")
        self.assertIn("not allowed", body["error_description"])


class ConsentDeniedTest(EndpointCase):
    def test_deny_redirects_with_access_denied_and_no_code(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id, state="keep-me")
        self.flow.signed_in(new_account())
        page = self.flow.consent_page(request_id)
        response = self.flow.decide(self.flow.form_fields(page), "deny")
        self.assertEqual(response.status_code, 303)
        location = response.headers["location"]
        self.assertTrue(location.startswith(REDIRECT_URI), location)
        params = query(location)
        self.assertEqual(params["error"], "access_denied")
        self.assertEqual(params["state"], "keep-me")
        self.assertNotIn("code", params)

    def test_a_decided_request_cannot_be_decided_again(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(new_account())
        fields = self.flow.form_fields(self.flow.consent_page(request_id))
        self.flow.decide(fields, "deny")
        self.assertEqual(self.flow.decide(fields, "approve").status_code, 400)

    def test_another_users_session_cannot_decide(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(new_account())
        fields = self.flow.form_fields(self.flow.consent_page(request_id))
        self.flow.signed_in(new_account())
        self.assertEqual(self.flow.decide(fields, "approve").status_code, 400)

    def test_another_user_viewing_the_page_does_not_take_the_request_over(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        owner = new_account()
        self.flow.signed_in(owner)
        fields = self.flow.form_fields(self.flow.consent_page(request_id))

        self.flow.signed_in(new_account())
        self.assertEqual(self.flow.consent_page(request_id).status_code, 400)

        self.flow.signed_in(owner)
        self.assertEqual(self.flow.decide(fields, "approve").status_code, 303)

    def test_a_wrong_form_value_is_refused_and_the_genuine_one_still_works(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(new_account())
        fields = self.flow.form_fields(self.flow.consent_page(request_id))
        forged = {**fields, "form": secrets.token_urlsafe(32)}
        self.assertEqual(self.flow.decide(forged, "approve").status_code, 400)
        self.assertEqual(self.flow.decide(fields, "approve").status_code, 303)

    def test_a_custom_scheme_redirect_shows_scheme_and_path(self):
        custom = "com.example.app:/oauth/callback"
        self.provider.allowed_redirect_uris = (custom,)
        response = self.flow.register(redirect_uris=[custom])
        self.assertEqual(response.status_code, 201, response.text)
        client_id = response.json()["client_id"]
        request_id = self.flow.consent_request(client_id, redirect_uri=custom)
        self.flow.signed_in(new_account())
        page = self.flow.consent_page(request_id)
        self.assertIn("<dt>Returns to</dt><dd>com.example.app:/oauth/callback</dd>", page.text)

    def test_the_page_names_the_approving_account(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        user_id = new_account()
        self.flow.signed_in(user_id)
        page = self.flow.consent_page(request_id)
        self.assertIn("Signed in as", page.text)
        self.assertIn(f"{user_id}@example.com", page.text)
        self.assertIn("Test user", page.text)

    def test_a_registered_client_name_is_labeled_as_unverified(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(new_account())
        page = self.flow.consent_page(request_id)
        self.assertIn("provided by the client, not verified", page.text)
        self.assertIn(CLIENT_NAME, page.text)

    def test_the_page_cannot_be_framed(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(new_account())
        page = self.flow.consent_page(request_id)
        self.assertEqual(page.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])


class IssuerParameterTest(EndpointCase):
    def issuer(self):
        return self.client.get("/.well-known/oauth-authorization-server").json()["issuer"]

    def test_the_metadata_advertises_it(self):
        metadata = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertIs(metadata["authorization_response_iss_parameter_supported"], True)

    def test_an_approval_carries_it(self):
        client_id = self.flow.registered_client_id()
        location = self.flow.approved_location(client_id, new_account())
        self.assertEqual(query(location)["iss"], self.issuer())

    def test_a_denial_carries_it(self):
        client_id = self.flow.registered_client_id()
        request_id = self.flow.consent_request(client_id)
        self.flow.signed_in(new_account())
        page = self.flow.consent_page(request_id)
        location = self.flow.decide(self.flow.form_fields(page), "deny").headers["location"]
        self.assertEqual(query(location)["iss"], self.issuer())

    def test_an_error_redirect_from_the_sdk_carries_it(self):
        client_id = self.flow.registered_client_id()
        response = self.flow.authorize(client_id, resource="https://other.example/mcp")
        self.assertEqual(query(response.headers["location"])["iss"], self.issuer())

    def test_the_redirect_to_the_consent_page_does_not(self):
        client_id = self.flow.registered_client_id()
        response = self.flow.authorize(client_id)
        self.assertNotIn("iss", query(response.headers["location"]))


class ConfidentialRegistrationTest(EndpointCase):
    """Dynamic registration of a client with a secret is refused.

    The SDK's client authenticator compares the presented secret with the stored plaintext, so a
    secret cannot be stored as a hash without replacing that SDK code.
    """

    def test_a_secret_based_registration_is_refused(self):
        for method in ("client_secret_post", "client_secret_basic"):
            response = self.flow.register(method=method)
            self.assertEqual(response.status_code, 400, response.text)
            self.assertEqual(response.json()["error"], "invalid_client_metadata")

    def test_the_metadata_advertises_no_secret_method(self):
        metadata = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertIn("none", metadata["token_endpoint_auth_methods_supported"])
        for method in ("client_secret_post", "client_secret_basic"):
            self.assertNotIn(method, metadata["token_endpoint_auth_methods_supported"])


if __name__ == "__main__":
    unittest.main()
