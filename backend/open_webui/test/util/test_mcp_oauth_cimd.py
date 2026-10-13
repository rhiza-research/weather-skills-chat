"""Clients identified by a Client ID Metadata Document.

The document fetch is replaced with a stand-in that returns a prepared response, except in the
private-address tests, which run the real SSRF checks with the HTTP client replaced by one that
fails the test if it is used.
"""

import json
import time
import unittest
import uuid
from contextlib import contextmanager
from unittest.mock import patch

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastmcp.server.auth import cimd, ssrf
from fastmcp.server.auth.auth import JWT_BEARER_ASSERTION_TYPE
from fastmcp.server.auth.ssrf import SSRFFetchResponse

from open_webui.test.util.test_mcp_oauth import (
    REDIRECT_URI,
    EndpointCase,
    new_account,
    query,
)

DOCUMENT_URL = "https://client.example/oauth/client.json"
DOCUMENT_CLIENT_NAME = "A metadata document client"


def document(**overrides):
    body = {
        "client_id": DOCUMENT_URL,
        "client_name": DOCUMENT_CLIENT_NAME,
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not None}


@contextmanager
def serving(body, headers=None):
    """Answer document fetches with `body`. Yields the list of fetched URLs."""
    fetched = []

    async def fetch(url, **kwargs):
        fetched.append(url)
        return SSRFFetchResponse(
            content=json.dumps(body).encode(), status_code=200, headers=dict(headers or {})
        )

    with patch.object(cimd, "ssrf_safe_fetch_response", fetch):
        yield fetched


@contextmanager
def no_http():
    """Fail the test if the SSRF module opens an HTTP client."""
    with patch.object(
        ssrf.httpx2, "AsyncClient", side_effect=AssertionError("an HTTP request was made")
    ) as client:
        yield client


class MetadataDocumentClientTest(EndpointCase):
    def test_the_metadata_advertises_metadata_documents(self):
        metadata = self.client.get("/.well-known/oauth-authorization-server").json()
        self.assertIs(metadata["client_id_metadata_document_supported"], True)

    def test_the_consent_page_shows_the_documents_client_name(self):
        with serving(document()):
            request_id = self.flow.consent_request(DOCUMENT_URL)
            self.flow.signed_in(new_account())
            page = self.flow.consent_page(request_id)
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn(DOCUMENT_CLIENT_NAME, page.text)

    def test_the_flow_completes(self):
        with serving(document()):
            code = self.flow.code(DOCUMENT_URL, new_account())
            response = self.flow.exchange(DOCUMENT_URL, code)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["access_token"])

    def test_the_flow_completes_without_redirect_uri_when_one_is_listed(self):
        with serving(document()):
            location = self.flow.approved_location(
                DOCUMENT_URL, new_account(), redirect_uri=None
            )
            self.assertTrue(location.startswith(REDIRECT_URI), location)
            response = self.flow.exchange(DOCUMENT_URL, query(location)["code"], redirect_uri=None)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["access_token"])

    def test_a_document_is_cached_by_default(self):
        with serving(document()) as fetched:
            self.flow.consent_request(DOCUMENT_URL)
            self.flow.consent_request(DOCUMENT_URL)
        self.assertEqual(fetched, [DOCUMENT_URL])

    def test_a_no_store_document_is_fetched_each_time(self):
        with serving(document(), headers={"Cache-Control": "no-store"}) as fetched:
            self.flow.consent_request(DOCUMENT_URL)
            self.flow.consent_request(DOCUMENT_URL)
        self.assertEqual(fetched, [DOCUMENT_URL, DOCUMENT_URL])


class ConsentPageTest(EndpointCase):
    def test_the_verified_client_id_url_is_shown(self):
        with serving(document()):
            request_id = self.flow.consent_request(DOCUMENT_URL)
            self.flow.signed_in(new_account())
            page = self.flow.consent_page(request_id)
        self.assertIn(DOCUMENT_URL, page.text)
        self.assertIn("verified document URL", page.text)
        self.assertNotIn("not verified", page.text)


def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(key, kid="test-key"):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return {**jwk, "kid": kid, "use": "sig", "alg": "RS256"}


def assertion(key, audience, kid="test-key"):
    now = int(time.time())
    return jwt.encode(
        {
            "iss": DOCUMENT_URL,
            "sub": DOCUMENT_URL,
            "aud": audience,
            "iat": now,
            "exp": now + 60,
            "jti": uuid.uuid4().hex,
        },
        key,
        algorithm="RS256",
        headers={"kid": kid},
    )


class PrivateKeyJwtTest(EndpointCase):
    """A metadata-document client authenticating with private_key_jwt and inline keys."""

    def setUp(self):
        super().setUp()
        self.key = signing_key()
        self.body = document(
            token_endpoint_auth_method="private_key_jwt",
            jwks={"keys": [public_jwk(self.key)]},
        )

    def _exchange(self, code, signed_with):
        return self.client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": DOCUMENT_URL,
                "code_verifier": self.flow.verifier,
                "client_assertion_type": JWT_BEARER_ASSERTION_TYPE,
                "client_assertion": assertion(signed_with, self.provider.token_endpoint_url),
            },
        )

    def test_a_signed_assertion_exchanges_the_code(self):
        with serving(self.body):
            code = self.flow.code(DOCUMENT_URL, new_account())
            response = self._exchange(code, self.key)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.flow.mcp_initialize(response.json()["access_token"]).status_code, 200)

    def test_an_assertion_signed_with_another_key_is_refused(self):
        with serving(self.body):
            code = self.flow.code(DOCUMENT_URL, new_account())
            response = self._exchange(code, signing_key())
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()["error"], "invalid_client")

    def test_no_assertion_is_refused(self):
        with serving(self.body):
            code = self.flow.code(DOCUMENT_URL, new_account())
            response = self.flow.exchange(DOCUMENT_URL, code)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()["error"], "invalid_client")

    def _access_token(self):
        code = self.flow.code(DOCUMENT_URL, new_account())
        response = self._exchange(code, self.key)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["access_token"]

    def test_revocation_with_a_signed_assertion(self):
        with serving(self.body):
            access = self._access_token()
            response = self.client.post(
                "/revoke",
                data={
                    "token": access,
                    "client_id": DOCUMENT_URL,
                    "client_assertion_type": JWT_BEARER_ASSERTION_TYPE,
                    "client_assertion": assertion(self.key, self.provider.token_endpoint_url),
                },
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.flow.mcp_initialize(access).status_code, 401)

    def test_revocation_without_an_assertion_is_refused(self):
        with serving(self.body):
            access = self._access_token()
            response = self.flow.revoke(DOCUMENT_URL, access)
        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(response.json()["error"], "invalid_client")
        self.assertEqual(self.flow.mcp_initialize(access).status_code, 200)


class MetadataDocumentRefusedTest(EndpointCase):
    def assertRefused(self, response):
        # The SDK answers an unknown client directly, without redirecting to the client.
        self.assertEqual(response.status_code, 400, response.text)
        self.assertNotIn("location", response.headers)
        self.assertEqual(response.json()["error"], "invalid_request")

    def test_a_different_client_id_in_the_document(self):
        with serving(document(client_id="https://client.example/oauth/other.json")):
            self.assertRefused(self.flow.authorize(DOCUMENT_URL))

    def test_a_client_id_that_differs_only_by_a_trailing_slash(self):
        with serving(document(client_id=f"{DOCUMENT_URL}/")):
            self.assertRefused(self.flow.authorize(DOCUMENT_URL))

    def test_a_document_without_redirect_uris(self):
        for redirect_uris in (None, []):
            with self.subTest(redirect_uris=redirect_uris), serving(
                document(redirect_uris=redirect_uris)
            ):
                self.assertRefused(self.flow.authorize(DOCUMENT_URL))
                self.provider.document_fetcher._cache.clear()

    def test_a_document_without_a_client_name(self):
        with serving(document(client_name=None)):
            self.assertRefused(self.flow.authorize(DOCUMENT_URL))

    def test_a_document_that_is_not_json(self):
        async def fetch(url, **kwargs):
            return SSRFFetchResponse(content=b"<html>", status_code=200, headers={})

        with patch.object(cimd, "ssrf_safe_fetch_response", fetch):
            self.assertRefused(self.flow.authorize(DOCUMENT_URL))

    def test_an_omitted_redirect_uri_with_two_listed_is_refused(self):
        body = document(redirect_uris=[REDIRECT_URI, "http://127.0.0.1:33418/other"])
        with serving(body):
            self.assertRefused(self.flow.authorize(DOCUMENT_URL, redirect_uri=None))

    def test_a_redirect_the_document_does_not_list(self):
        with serving(document()):
            self.assertRefused(
                self.flow.authorize(DOCUMENT_URL, redirect_uri="http://127.0.0.1:33418/other")
            )

    def test_a_listed_redirect_the_policy_refuses(self):
        remote = "https://client.example/callback"
        with serving(document(redirect_uris=[remote])):
            self.assertRefused(self.flow.authorize(DOCUMENT_URL, redirect_uri=remote))

    def test_private_key_jwt_without_inline_keys(self):
        # Fetching a jwks_uri would be an outbound call other than the document fetch.
        body = document(
            token_endpoint_auth_method="private_key_jwt",
            jwks_uri="https://client.example/jwks.json",
        )
        with serving(body):
            self.assertRefused(self.flow.authorize(DOCUMENT_URL))

    def test_a_non_https_client_id_is_not_fetched(self):
        with serving(document()) as fetched:
            self.assertRefused(self.flow.authorize("http://client.example/oauth/client.json"))
        self.assertEqual(fetched, [])

    def test_a_private_address_is_not_fetched(self):
        for client_id in (
            "https://10.0.0.1/oauth/client.json",
            "https://127.0.0.1/oauth/client.json",
            "https://169.254.169.254/oauth/client.json",
        ):
            with self.subTest(client_id=client_id), no_http() as http_client:
                self.assertRefused(self.flow.authorize(client_id))
                http_client.assert_not_called()

    def test_the_token_endpoint_refuses_an_unusable_document(self):
        with serving(document(client_id="https://client.example/oauth/other.json")):
            response = self.flow.exchange(DOCUMENT_URL, "a-code")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"], "invalid_client")

    def test_an_approval_redirect_goes_only_to_a_listed_uri(self):
        with serving(document()):
            location = self.flow.approved_location(DOCUMENT_URL, new_account())
        self.assertTrue(location.startswith(REDIRECT_URI), location)
        self.assertIn("code", query(location))


if __name__ == "__main__":
    unittest.main()
