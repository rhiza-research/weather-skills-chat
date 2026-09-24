"""The endpoint is always built, with the provider build_auth_provider returns.

Also the exact form of the resource identifier. A client refuses a wrong identifier without this
service reporting an error.
"""

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.config import WEBUI_URL
from open_webui.mcp import build_endpoint
from open_webui.mcp.auth import MCP_PATH, canonical_resource_identifier
from open_webui.test.util.mcp_stub_auth import stub_auth, stub_auth_provider

SERVICE_URL = "https://chat.example"
IDENTIFIER = f"{SERVICE_URL}{MCP_PATH}"
HOST_APP = SimpleNamespace(state=SimpleNamespace(TOOLS={}))


@contextmanager
def base_url(value):
    """Set WEBUI_URL, then restore it.

    unittest.mock cannot patch it: it reads the target's __dict__, and PersistentConfig raises
    TypeError for __dict__.
    """
    previous = WEBUI_URL.value
    WEBUI_URL.value = value
    try:
        yield
    finally:
        WEBUI_URL.value = previous


class CanonicalResourceIdentifierTest(unittest.TestCase):
    def test_one_path_segment_and_no_trailing_slash(self):
        with base_url(SERVICE_URL):
            self.assertEqual(canonical_resource_identifier(), IDENTIFIER)

    def test_a_trailing_slash_on_the_service_url_changes_nothing(self):
        with base_url(f"{SERVICE_URL}/"):
            self.assertEqual(canonical_resource_identifier(), IDENTIFIER)

    def test_refuses_when_the_service_url_is_empty(self):
        with base_url(""):
            with self.assertRaises(RuntimeError) as raised:
                canonical_resource_identifier()
            self.assertIn("WEBUI_URL", str(raised.exception))


class BuildEndpointTest(unittest.TestCase):
    def test_an_endpoint_is_built(self):
        with base_url(SERVICE_URL), stub_auth():
            built = build_endpoint(HOST_APP)
        self.assertIsNotNone(built.asgi_app)

    def test_the_server_authenticates_with_the_provider_build_auth_provider_returns(self):
        provider = None

        def build():
            nonlocal provider
            provider = stub_auth_provider()
            return provider

        with base_url(SERVICE_URL), patch(
            "open_webui.mcp.build_auth_provider", side_effect=build
        ), patch("open_webui.mcp.FastMCP") as server:
            build_endpoint(HOST_APP)
        self.assertIsNotNone(provider)
        self.assertIs(server.call_args.kwargs["auth"], provider)

    def test_an_empty_service_url_raises_instead_of_leaving_the_endpoint_unserved(self):
        with base_url(""), stub_auth():
            with self.assertRaises(RuntimeError) as raised:
                build_endpoint(HOST_APP)
            self.assertIn("WEBUI_URL", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
