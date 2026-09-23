"""A request without a credential gets a 401 with a challenge naming the metadata document.

The tests send requests through the ASGI app and check the response a client receives.

The challenge-following tests use a host application that also mounts an interface stand-in at the
root. A document route registered after the stand-in is shadowed by it, as in the real app.
"""

import asyncio
import datetime
import functools
import re
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.server.auth.providers.jwt import JWTVerifier
from starlette.testclient import TestClient

from open_webui.config import OPENID_PROVIDER_URL, WEBUI_URL
from open_webui.mcp import PROTECTED_RESOURCE_PREFIX, SERVED_PATH, build_endpoint
from open_webui.mcp.auth import (
    MCP_PATH,
    OIDC_DISCOVERY_SUFFIX,
    NoAdvertisedScopesProvider,
    build_auth_provider,
)
from open_webui.test.util.mcp_host import host_application

REALM = "https://provider.example/realms/weather"
DISCOVERY_URL = f"{REALM}{OIDC_DISCOVERY_SUFFIX}"
SERVICE_URL = "https://chat.example"
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


@contextmanager
def configured():
    previous = (OPENID_PROVIDER_URL.value, WEBUI_URL.value)
    OPENID_PROVIDER_URL.value = DISCOVERY_URL
    WEBUI_URL.value = SERVICE_URL
    try:
        yield
    finally:
        OPENID_PROVIDER_URL.value, WEBUI_URL.value = previous


@functools.lru_cache(maxsize=1)
def signing_keypair():
    """A local RSA keypair for minting and verifying tokens without network access."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def mint(claims):
    """A signed token with the given claims plus iss, sub, iat, and exp."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return jwt.encode(
        {
            "iss": REALM,
            "sub": "a-subject",
            "iat": now,
            "exp": now + datetime.timedelta(minutes=5),
            **claims,
        },
        signing_keypair()[0],
        algorithm="RS256",
    )


def verifier(**overrides):
    """A verifier with the endpoint's settings and the local public key."""
    settings = {
        "public_key": signing_keypair()[1],
        "issuer": REALM,
        "audience": IDENTIFIER,
        "algorithm": "RS256",
        "required_scopes": ["openid"],
    }
    settings.update(overrides)
    return JWTVerifier(**settings)


def built_endpoint(case):
    """The built endpoint. Fails the test if none was built."""
    with configured():
        endpoint = build_endpoint(HOST_APP)
    case.assertIsNotNone(endpoint, "no endpoint was built from a configured provider")
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


class AdvertisedScopesTest(unittest.TestCase):
    """The document has no scopes_supported field, and the challenge names the required scope.

    A client that copies scopes_supported into its dynamic registration cannot later request a
    scope outside that list. The challenge is where a client learns the required scope instead.
    """

    def setUp(self):
        self.endpoint = built_endpoint(self)
        with configured():
            self.required = build_auth_provider().challenge_scopes

    def _document(self):
        with host_application(self.endpoint) as client:
            return client.get(f"{PROTECTED_RESOURCE_PREFIX}{MCP_PATH}").json()

    def test_the_document_carries_no_scope_list(self):
        # RFC 9728 makes the field optional. It must be absent, because a client can also copy an
        # empty list into its registration.
        self.assertNotIn("scopes_supported", self._document())

    def test_the_document_still_carries_what_a_client_needs(self):
        document = self._document()
        self.assertEqual(document["resource"], IDENTIFIER)
        self.assertEqual(document["authorization_servers"], [REALM])

    def test_the_challenge_still_names_the_scope(self):
        with host_application(self.endpoint) as client:
            response = client.post(
                SERVED_PATH,
                json=INITIALIZE_REQUEST,
                headers={"Accept": "application/json, text/event-stream"},
            )
        challenge = response.headers.get("www-authenticate")
        self.assertIsNotNone(challenge, "the refusal carried no challenge header")
        self.assertTrue(self.required, "the provider requires no scope to name")
        for scope in self.required:
            self.assertIn(scope, challenge)


class RequiredScopeStillEnforcedTest(unittest.TestCase):
    """Token verification requires the openid scope, which the document does not advertise.

    By default the library reads the advertised and required scopes from one setting.
    NoAdvertisedScopesProvider separates them. Tokens are signed with the local keypair. The 401
    for a token that fails verification is covered by the junk-token test above.
    """

    def _verify(self, scope):
        provider = NoAdvertisedScopesProvider(
            realm_url=REALM, base_url=IDENTIFIER, token_verifier=verifier()
        )
        claims = {"aud": IDENTIFIER}
        if scope is not None:
            claims["scope"] = scope
        return asyncio.run(provider.verify_token(mint(claims)))

    def test_a_token_carrying_the_scope_verifies(self):
        # Control case for the refusals below.
        self.assertIsNotNone(self._verify("openid"))

    def test_a_token_without_the_scope_is_refused(self):
        self.assertIsNone(self._verify("profile email"))

    def test_a_token_with_no_scope_claim_is_refused(self):
        self.assertIsNone(self._verify(None))

    def test_the_advertised_and_required_sets_are_now_separate(self):
        provider = NoAdvertisedScopesProvider(
            realm_url=REALM, base_url=IDENTIFIER, token_verifier=verifier()
        )
        self.assertIsNone(provider.scopes_supported)
        self.assertEqual(provider.required_scopes, ["openid"])


class AudienceAcceptedInsideAListTest(unittest.TestCase):
    """The verifier accepts this endpoint's audience as a string or as a member of a list.

    With the realm's default roles, the imported sign-in user's tokens carry
    `aud: [<endpoint>, "account"]`.
    """

    def _verify(self, audience):
        return asyncio.run(
            verifier().verify_token(mint({"aud": audience, "scope": "openid"}))
        )

    def test_the_audience_alone_is_accepted(self):
        self.assertIsNotNone(self._verify(IDENTIFIER))

    def test_the_audience_inside_a_list_is_accepted(self):
        self.assertIsNotNone(self._verify([IDENTIFIER, "account"]))

    def test_a_list_without_the_audience_is_refused(self):
        self.assertIsNone(self._verify(["account"]))

    def test_a_missing_audience_is_refused(self):
        # A token has no aud claim when the user holds no realm roles, because the scope with the
        # audience mapper is not applied.
        self.assertIsNone(
            asyncio.run(verifier().verify_token(mint({"scope": "openid"})))
        )


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
