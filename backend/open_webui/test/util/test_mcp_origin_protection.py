"""Origin protection on the endpoint.

A request from a foreign Origin gets 403. A request with no Origin header is not refused for that,
because agents usually send none.
"""

import unittest
from types import SimpleNamespace
from contextlib import contextmanager

from starlette.testclient import TestClient

from open_webui.config import OPENID_PROVIDER_URL, WEBUI_URL
from open_webui.mcp import build_endpoint
from open_webui.mcp.auth import (
    MCP_PATH,
    OIDC_DISCOVERY_SUFFIX,
    canonical_resource_identifier,
    service_origin,
)

REALM = "https://provider.example/realms/weather"
DISCOVERY_URL = f"{REALM}{OIDC_DISCOVERY_SUFFIX}"
SERVICE_URL = "https://chat.example"
HOSTILE_ORIGIN = "https://attacker.example"
HOST_APP = SimpleNamespace(state=SimpleNamespace(TOOLS={}))

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


class ServiceOriginTest(unittest.TestCase):
    def test_origin_is_the_identifier_without_its_path(self):
        # An Origin header has no path, so it is compared to the identifier without its path.
        with configured():
            self.assertEqual(service_origin(), SERVICE_URL)
            self.assertEqual(canonical_resource_identifier(), f"{SERVICE_URL}{MCP_PATH}")

    def test_the_origin_carries_no_path(self):
        with configured():
            self.assertNotIn(MCP_PATH, service_origin())


class OriginGuardTest(unittest.TestCase):
    def setUp(self):
        with configured():
            self.app = build_endpoint(HOST_APP).asgi_app

    def _post(self, headers):
        with TestClient(self.app, base_url=SERVICE_URL) as client:
            return client.post(
                "/",
                json=INITIALIZE_REQUEST,
                headers={
                    "Accept": "application/json, text/event-stream",
                    **headers,
                },
            )

    def test_a_request_with_no_origin_is_not_refused_for_that(self):
        # The unauthenticated request gets 401 from the auth layer, not 403 from the Origin check.
        self.assertNotEqual(self._post({}).status_code, 403)

    def test_a_hostile_origin_is_refused(self):
        self.assertEqual(self._post({"Origin": HOSTILE_ORIGIN}).status_code, 403)

    def test_the_service_own_origin_is_allowed_through_to_auth(self):
        # The request passes the Origin check and reaches the auth layer, which refuses it.
        self.assertNotEqual(self._post({"Origin": SERVICE_URL}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
