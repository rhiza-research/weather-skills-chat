"""That the endpoint is always served, and the exact form of the resource identifier and issuer.

A client refuses a wrong identifier or issuer without this service reporting an error.
"""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from open_webui.mcp import build_endpoint
from open_webui.mcp.auth import (
    MCP_PATH,
    build_auth_provider,
    canonical_resource_identifier,
    service_url,
)
from open_webui.mcp_oauth.provider import EndpointOAuthProvider
from open_webui.test.util.mcp_host import (
    SERVICE_URL,
    host_application,
    service_configured,
)

IDENTIFIER = f"{SERVICE_URL}{MCP_PATH}"
HOST_APP = SimpleNamespace(state=SimpleNamespace(TOOLS={}))


class CanonicalResourceIdentifierTest(unittest.TestCase):
    def test_one_path_segment_and_no_trailing_slash(self):
        with service_configured(SERVICE_URL):
            self.assertEqual(canonical_resource_identifier(), IDENTIFIER)

    def test_a_trailing_slash_on_the_service_url_changes_nothing(self):
        with service_configured(f"{SERVICE_URL}/"):
            self.assertEqual(canonical_resource_identifier(), IDENTIFIER)
            self.assertEqual(service_url(), SERVICE_URL)

    def test_refuses_when_the_service_url_is_empty(self):
        with service_configured(""):
            with self.assertRaises(RuntimeError) as raised:
                canonical_resource_identifier()
            self.assertIn("WEBUI_URL", str(raised.exception))


class BuildAuthProviderTest(unittest.TestCase):
    """The settings build_auth_provider passes to the built-in authorization server."""

    def setUp(self):
        with service_configured(SERVICE_URL):
            self.built = build_auth_provider()

    def test_it_is_the_built_in_authorization_server(self):
        self.assertIsInstance(self.built, EndpointOAuthProvider)

    def test_tokens_are_for_the_canonical_identifier(self):
        self.assertEqual(self.built.resource_identifier, IDENTIFIER)

    def test_the_issuer_is_the_service(self):
        issuer = urlsplit(self.built.issuer)
        self.assertEqual(f"{issuer.scheme}://{issuer.netloc}", SERVICE_URL)
        self.assertIn(issuer.path, ("", "/"))

    def test_the_metadata_advertises_the_issuer_the_provider_sends(self):
        # Clients compare the metadata issuer and the redirect's iss byte for byte (RFC 9207).
        with service_configured(SERVICE_URL):
            endpoint = build_endpoint(HOST_APP)
        with host_application(endpoint) as client:
            metadata = client.get("/.well-known/oauth-authorization-server").json()
        self.assertEqual(metadata["issuer"], endpoint.provider.issuer)

    def test_the_rate_limiter_uses_redis_when_redis_url_is_set(self):
        connection = object()
        with service_configured(SERVICE_URL), patch(
            "open_webui.mcp_oauth.limits.REDIS_URL", "redis://redis:6379/0"
        ), patch(
            "open_webui.utils.redis.get_redis_connection", return_value=connection
        ) as connect:
            built = build_auth_provider()
        self.assertIs(built.rate_limiter.redis, connection)
        self.assertEqual(connect.call_args.args[0], "redis://redis:6379/0")

    def test_allowed_redirect_uris_are_read_from_the_environment(self):
        with service_configured(SERVICE_URL), patch.dict(
            os.environ,
            {"MCP_OAUTH_ALLOWED_REDIRECT_URIS": " https://a.example/cb, https://b.example/* "},
        ):
            built = build_auth_provider()
        self.assertEqual(
            built.allowed_redirect_uris, ("https://a.example/cb", "https://b.example/*")
        )

    def test_the_rate_limiter_counts_in_process_without_redis_url(self):
        with service_configured(SERVICE_URL), patch("open_webui.mcp_oauth.limits.REDIS_URL", ""):
            self.assertIsNone(build_auth_provider().rate_limiter.redis)

    def test_no_scope_is_required(self):
        self.assertEqual(list(self.built.required_scopes), [])


class BuildEndpointTest(unittest.TestCase):
    def test_an_empty_service_url_stops_startup(self):
        with service_configured(""):
            with self.assertRaises(RuntimeError) as raised:
                build_endpoint(HOST_APP)
        self.assertIn("WEBUI_URL", str(raised.exception))

    def test_an_endpoint_when_the_service_url_is_set(self):
        with service_configured(SERVICE_URL):
            built = build_endpoint(HOST_APP)
        self.assertIsNotNone(built)
        self.assertIsNotNone(built.asgi_app)

    def test_a_localhost_http_address_is_served(self):
        # The local stack runs at http://localhost.
        with service_configured("http://localhost:3000"):
            self.assertIsNotNone(build_endpoint(HOST_APP))

    def test_a_service_url_with_no_scheme_stops_startup_naming_the_value(self):
        with service_configured("chat.example"):
            with self.assertRaises(RuntimeError) as raised:
                build_endpoint(HOST_APP)
        self.assertIn(repr("chat.example"), str(raised.exception))

    def test_an_issuer_the_sdk_refuses_stops_startup_naming_the_value(self):
        # The SDK requires https unless the host is a loopback name.
        with service_configured("http://chat.example"):
            with self.assertRaises(RuntimeError) as raised:
                build_endpoint(HOST_APP)
        self.assertIn(repr("http://chat.example"), str(raised.exception))


if __name__ == "__main__":
    unittest.main()
