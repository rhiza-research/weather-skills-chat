"""A request without a credential gets a 401 with a challenge naming the metadata document.

The tests send requests through the ASGI app and check the response a client receives.

The challenge-following tests use a host application that also mounts an interface stand-in at the
root. A document route registered after the stand-in is shadowed by it, as in the real app.
"""

import re
import unittest
from types import SimpleNamespace
from urllib.parse import urlsplit

from starlette.testclient import TestClient

from open_webui.mcp import PROTECTED_RESOURCE_PREFIX, SERVED_PATH, build_endpoint
from open_webui.mcp.auth import MCP_PATH
from open_webui.test.util.mcp_host import (
    SERVICE_URL,
    host_application,
    service_configured,
)

IDENTIFIER = f"{SERVICE_URL}{MCP_PATH}"
HOST_APP = SimpleNamespace(state=SimpleNamespace(TOOLS={}))

# RFC 9728 puts the document's URL in this parameter of the challenge, quoted.
RESOURCE_METADATA = re.compile(r'resource_metadata="([^"]*)"')

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


def built_endpoint(case):
    """The built endpoint. Fails the test if none was built."""
    with service_configured():
        endpoint = build_endpoint(HOST_APP)
    case.assertIsNotNone(endpoint, "no endpoint was built for a configured service URL")
    return endpoint


class UncredentialedRequestTest(unittest.TestCase):
    def setUp(self):
        self.app = built_endpoint(self).asgi_app

    def _post(self, headers=None):
        with TestClient(self.app) as client:
            return client.post(
                "/",
                json=INITIALIZE_REQUEST,
                headers={
                    "Accept": "application/json, text/event-stream",
                    **(headers or {}),
                },
            )

    def _challenge(self):
        response = self._post()
        challenge = response.headers.get("www-authenticate")
        self.assertIsNotNone(challenge, "the refusal carried no challenge header")
        return challenge

    def test_no_credential_is_refused(self):
        self.assertEqual(self._post().status_code, 401)

    def test_the_refusal_carries_a_challenge(self):
        # A client reads the challenge to find where to authenticate.
        self.assertIn("www-authenticate", {k.lower() for k in self._post().headers})

    def test_the_challenge_names_the_metadata_document(self):
        self.assertIn("resource_metadata", self._challenge())

    def test_the_challenge_points_at_this_service(self):
        self.assertIn(SERVICE_URL, self._challenge())

    def test_a_bearer_scheme_is_named(self):
        self.assertIn("Bearer", self._challenge())

    def test_a_junk_token_is_also_refused(self):
        response = self._post({"Authorization": "Bearer not-a-real-token"})
        self.assertEqual(response.status_code, 401)

    def test_an_interface_style_cookie_does_not_authenticate(self):
        # The interface accepts a `token` cookie. The endpoint does not.
        response = self._post({"Cookie": "token=an-interface-session-token"})
        self.assertEqual(response.status_code, 401)


class ProtectedResourceDocumentTest(unittest.TestCase):
    """The document names this service as the authorization server and has no scope list.

    A client that copies scopes_supported into its dynamic registration cannot later request a
    scope outside that list. No scope is required.
    """

    def setUp(self):
        self.endpoint = built_endpoint(self)

    def _document(self):
        with host_application(self.endpoint) as client:
            return client.get(f"{PROTECTED_RESOURCE_PREFIX}{MCP_PATH}").json()

    def test_the_document_carries_no_scope_list(self):
        # RFC 9728 makes the field optional. It must be absent, because a client can also copy an
        # empty list into its registration.
        self.assertNotIn("scopes_supported", self._document())

    def test_the_document_carries_what_a_client_needs(self):
        document = self._document()
        self.assertEqual(document["resource"], IDENTIFIER)
        # A client looks up the authorization server by this value and requires the metadata
        # issuer to equal it exactly (RFC 8414 §3.3).
        with host_application(self.endpoint) as client:
            issuer = client.get("/.well-known/oauth-authorization-server").json()["issuer"]
        self.assertEqual(document["authorization_servers"], [issuer])
        self.assertEqual(issuer, self.endpoint.provider.issuer)


class ChallengeIsFollowableTest(unittest.TestCase):
    """The challenge's resource_metadata URL is on this service, and its path returns the document.

    A client fetches that exact URL. A mismatch such as a trailing slash returns the interface's
    HTML page instead of the document. The test client can request only the path, so scheme and
    host are checked separately.
    """

    def setUp(self):
        self.endpoint = built_endpoint(self)
        self.registered = [route.path for route in self.endpoint.root_routes]

    def _named_url(self, client):
        response = client.post(
            SERVED_PATH,
            json=INITIALIZE_REQUEST,
            headers={"Accept": "application/json, text/event-stream"},
        )
        self.assertEqual(response.status_code, 401)
        challenge = response.headers.get("www-authenticate")
        self.assertIsNotNone(challenge, "the refusal carried no challenge header")
        match = RESOURCE_METADATA.search(challenge)
        self.assertIsNotNone(match, challenge)
        named = match.group(1)
        self.assertTrue(named, f"the challenge named an empty URL: {challenge}")
        return named

    def test_the_url_the_challenge_names_is_on_this_service(self):
        with host_application(self.endpoint) as client:
            named = urlsplit(self._named_url(client))
        expected = urlsplit(SERVICE_URL)
        self.assertEqual(
            (named.scheme, named.netloc), (expected.scheme, expected.netloc)
        )

    def test_the_url_the_challenge_names_is_a_registered_path(self):
        with host_application(self.endpoint) as client:
            named = self._named_url(client)
        self.assertIn(urlsplit(named).path, self.registered)

    def test_the_url_the_challenge_names_yields_the_document(self):
        with host_application(self.endpoint) as client:
            named = self._named_url(client)
            response = client.get(urlsplit(named).path)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response.headers["content-type"])

    def test_the_document_advertises_the_canonical_identifier(self):
        # A client refuses the document when its resource value differs from the identifier the
        # well-known suffix was inserted into.
        with host_application(self.endpoint) as client:
            named = self._named_url(client)
            document = client.get(urlsplit(named).path).json()
        self.assertEqual(document["resource"], IDENTIFIER)

    def test_the_bare_metadata_prefix_yields_the_document_too(self):
        # Clients fall back to this path when the named one fails.
        with host_application(self.endpoint) as client:
            response = client.get(PROTECTED_RESOURCE_PREFIX)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
