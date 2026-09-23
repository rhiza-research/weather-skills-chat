"""That the endpoint is always served, and the exact form of the resource identifier.

A client refuses a wrong identifier without this service reporting an error.
"""

import os
import unittest
from types import SimpleNamespace
from contextlib import contextmanager
from unittest.mock import patch

from open_webui.config import OPENID_PROVIDER_URL, WEBUI_URL
from open_webui.mcp import build_endpoint
from open_webui.mcp.auth import (
    MCP_PATH,
    OIDC_DISCOVERY_SUFFIX,
    PUBLIC_REALM_URL_ENV,
    build_auth_provider,
    canonical_resource_identifier,
    public_realm_url,
    realm_url,
)

REALM = "https://provider.example/realms/weather"
DISCOVERY_URL = f"{REALM}{OIDC_DISCOVERY_SUFFIX}"
SERVICE_URL = "https://chat.example"
IDENTIFIER = f"{SERVICE_URL}{MCP_PATH}"
HOST_APP = SimpleNamespace(state=SimpleNamespace(TOOLS={}))


@contextmanager
def config(provider_url, base_url):
    """Set both settings the endpoint reads, then restore them.

    unittest.mock cannot patch these: it reads the target's __dict__, and PersistentConfig raises
    TypeError for __dict__.
    """
    previous = (OPENID_PROVIDER_URL.value, WEBUI_URL.value)
    OPENID_PROVIDER_URL.value = provider_url
    WEBUI_URL.value = base_url
    try:
        yield
    finally:
        OPENID_PROVIDER_URL.value, WEBUI_URL.value = previous


class CanonicalResourceIdentifierTest(unittest.TestCase):
    def test_one_path_segment_and_no_trailing_slash(self):
        with config(DISCOVERY_URL, SERVICE_URL):
            self.assertEqual(canonical_resource_identifier(), IDENTIFIER)

    def test_a_trailing_slash_on_the_service_url_changes_nothing(self):
        with config(DISCOVERY_URL, f"{SERVICE_URL}/"):
            self.assertEqual(canonical_resource_identifier(), IDENTIFIER)

    def test_refuses_when_the_service_url_is_empty(self):
        with config(DISCOVERY_URL, ""):
            with self.assertRaises(RuntimeError) as raised:
                canonical_resource_identifier()
            self.assertIn("WEBUI_URL", str(raised.exception))


class RealmUrlTest(unittest.TestCase):
    def test_realm_is_the_discovery_url_without_the_suffix(self):
        with config(DISCOVERY_URL, SERVICE_URL):
            self.assertEqual(realm_url(), REALM)

    def test_a_trailing_slash_on_the_discovery_url_changes_nothing(self):
        with config(f"{DISCOVERY_URL}/", SERVICE_URL):
            self.assertEqual(realm_url(), REALM)

    def test_refuses_a_url_that_is_not_a_discovery_url(self):
        with config(REALM, SERVICE_URL):
            with self.assertRaises(RuntimeError) as raised:
                realm_url()
            self.assertIn(OIDC_DISCOVERY_SUFFIX, str(raised.exception))


class BuildAuthProviderTest(unittest.TestCase):
    """The settings build_auth_provider passes to the provider and its token verifier."""

    def setUp(self):
        with config(DISCOVERY_URL, SERVICE_URL):
            self.built = build_auth_provider()

    def test_audience_is_the_canonical_identifier(self):
        # The required audience equals the advertised resource, so a token issued for that
        # resource is accepted.
        self.assertEqual(self.built.token_verifier.audience, IDENTIFIER)

    def test_issuer_is_the_realm(self):
        # A token issued by another realm on the same host is refused.
        self.assertEqual(self.built.token_verifier.issuer, REALM)

    def test_keys_are_fetched_from_the_realm(self):
        self.assertTrue(self.built.token_verifier.jwks_uri.startswith(REALM))

    def test_the_advertised_resource_is_the_canonical_identifier(self):
        # base_url is the resource the metadata advertises. RFC 9728 requires it to equal the
        # identifier the well-known suffix was inserted into, including any trailing slash.
        self.assertEqual(str(self.built.base_url).rstrip("/"), IDENTIFIER)

    def test_the_provider_is_the_only_authorization_server_advertised(self):
        self.assertEqual(
            [str(server).rstrip("/") for server in self.built.authorization_servers],
            [REALM],
        )

    def test_only_openid_is_required(self):
        # A browser sign-in token carries openid. The openid scope guarantees the sub claim the
        # account lookup uses.
        self.assertEqual(list(self.built.required_scopes), ["openid"])


class PublicRealmUrlTest(unittest.TestCase):
    """MCP_PUBLIC_REALM_URL set: clients use it, and keys are fetched from OPENID_PROVIDER_URL."""

    PUBLIC_REALM = "http://localhost:8081/realms/weather"

    def setUp(self):
        with config(DISCOVERY_URL, SERVICE_URL), patch.dict(
            os.environ, {PUBLIC_REALM_URL_ENV: f"{self.PUBLIC_REALM}/"}
        ):
            self.built = build_auth_provider()

    def test_issuer_is_the_public_realm(self):
        self.assertEqual(self.built.token_verifier.issuer, self.PUBLIC_REALM)

    def test_the_public_realm_is_the_advertised_authorization_server(self):
        self.assertEqual(
            [str(server).rstrip("/") for server in self.built.authorization_servers],
            [self.PUBLIC_REALM],
        )

    def test_keys_are_fetched_from_the_realm_this_service_reaches(self):
        self.assertTrue(self.built.token_verifier.jwks_uri.startswith(REALM))

    def test_audience_is_still_the_canonical_identifier(self):
        self.assertEqual(self.built.token_verifier.audience, IDENTIFIER)

    def test_an_empty_value_means_unset(self):
        with config(DISCOVERY_URL, SERVICE_URL), patch.dict(
            os.environ, {PUBLIC_REALM_URL_ENV: "  "}
        ):
            self.assertEqual(public_realm_url(), REALM)


class BuildEndpointTest(unittest.TestCase):
    def test_an_unset_provider_url_stops_startup(self):
        with config("", SERVICE_URL):
            with self.assertRaises(RuntimeError) as raised:
                build_endpoint(HOST_APP)
        self.assertIn("OPENID_PROVIDER_URL", str(raised.exception))

    def test_a_provider_url_that_is_not_a_discovery_url_stops_startup(self):
        with config(REALM, SERVICE_URL):
            with self.assertRaises(RuntimeError) as raised:
                build_endpoint(HOST_APP)
        self.assertIn("OPENID_PROVIDER_URL", str(raised.exception))
        self.assertIn(repr(REALM), str(raised.exception))

    def test_an_endpoint_when_a_provider_is_configured(self):
        with config(DISCOVERY_URL, SERVICE_URL):
            built = build_endpoint(HOST_APP)
        self.assertIsNotNone(built)
        self.assertIsNotNone(built.asgi_app)

    def test_refuses_when_half_configured(self):
        with config(DISCOVERY_URL, ""):
            with self.assertRaises(RuntimeError):
                build_endpoint(HOST_APP)


if __name__ == "__main__":
    unittest.main()
