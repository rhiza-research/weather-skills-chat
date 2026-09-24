"""Discovery routes are registered at the root, ahead of the interface's catch-all.

Clients request root-absolute discovery paths, which a route inside the mounted app cannot answer.
Requests here go through a host application with an interface stand-in at the root, so a route
registered in the wrong place is shadowed by it.

The docstring of `_metadata_redirect_routes` explains which paths redirect.
"""

import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import urlsplit

from starlette.responses import PlainTextResponse
from starlette.routing import Route

from open_webui.config import OPENID_PROVIDER_URL, WEBUI_URL
from open_webui.mcp import (
    MCP_PATH,
    PROTECTED_RESOURCE_PREFIX,
    REDIRECT_STATUS,
    SERVED_PATH,
    _metadata_redirect_routes,
    build_endpoint,
)
from open_webui.mcp.auth import OIDC_DISCOVERY_SUFFIX
from open_webui.test.util.mcp_host import host_application

REALM = "https://provider.example/realms/weather"
DISCOVERY_URL = f"{REALM}{OIDC_DISCOVERY_SUFFIX}"
SERVICE_URL = "https://chat.example"
WELL_KNOWN_PREFIX = "/.well-known/"
DOCUMENT_PATH = f"{PROTECTED_RESOURCE_PREFIX}{MCP_PATH}"
HOST_APP = SimpleNamespace(state=SimpleNamespace(TOOLS={}))


@contextmanager
def configured():
    previous = (OPENID_PROVIDER_URL.value, WEBUI_URL.value)
    OPENID_PROVIDER_URL.value = DISCOVERY_URL
    WEBUI_URL.value = SERVICE_URL
    try:
        yield
    finally:
        OPENID_PROVIDER_URL.value, WEBUI_URL.value = previous


def built_endpoint(case):
    """The built endpoint. Fails the test if none was built."""
    with configured():
        endpoint = build_endpoint(HOST_APP)
    case.assertIsNotNone(endpoint, "no endpoint was built from a configured provider")
    return endpoint


def redirect_target(case, response):
    """The path component of a redirect response's Location header."""
    case.assertEqual(response.status_code, REDIRECT_STATUS)
    return urlsplit(response.headers["location"]).path


class RootRoutesTest(unittest.TestCase):
    def setUp(self):
        self.endpoint = built_endpoint(self)
        self.paths = [route.path for route in self.endpoint.root_routes]

    def test_there_is_a_route_for_the_bare_path(self):
        self.assertIn(MCP_PATH, self.paths)

    def test_the_protected_resource_document_is_at_the_exact_path(self):
        # RFC 9728 inserts the well-known segment after the authority, so clients request this
        # exact path. Checking only the prefix would miss a doubled /mcp/mcp path.
        self.assertIn(DOCUMENT_PATH, self.paths)

    def test_both_paths_that_lead_to_the_document_are_registered(self):
        self.assertIn(f"{DOCUMENT_PATH}/", self.paths)
        self.assertIn(PROTECTED_RESOURCE_PREFIX, self.paths)

    def test_no_discovery_path_repeats_the_endpoint_path(self):
        # At most one, not exactly one: the bare prefix contains no endpoint path and is also
        # registered.
        for path in self.paths:
            if path.startswith(WELL_KNOWN_PREFIX):
                self.assertLessEqual(path.count(MCP_PATH), 1, path)

    def test_every_discovery_path_is_root_absolute(self):
        # A path not starting at the root would be served under the mount.
        for path in self.paths:
            if WELL_KNOWN_PREFIX.strip("/") in path:
                self.assertTrue(path.startswith(WELL_KNOWN_PREFIX), path)

    def test_no_discovery_path_sits_under_the_mount(self):
        for path in self.paths:
            self.assertFalse(path.startswith(f"{MCP_PATH}/"), path)

    def test_the_mount_path_is_the_canonical_path(self):
        self.assertEqual(self.endpoint.mount_path, MCP_PATH)


class InterfaceStandInTest(unittest.TestCase):
    """The interface stand-in answers unregistered paths with HTML."""

    def test_an_unregistered_path_reaches_the_interface(self):
        endpoint = built_endpoint(self)
        with host_application(endpoint) as client:
            response = client.get("/some/page/the/interface/serves")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["content-type"])


class BarePathTest(unittest.TestCase):
    """The bare endpoint path redirects to the served path instead of returning the interface."""

    def setUp(self):
        self.endpoint = built_endpoint(self)

    def test_a_get_redirects_to_the_served_path(self):
        with host_application(self.endpoint, follow_redirects=False) as client:
            response = client.get(MCP_PATH)
        self.assertEqual(redirect_target(self, response), SERVED_PATH)

    def test_a_post_redirects_too(self):
        # 307 and 308 preserve the method and body; 302 does not.
        with host_application(self.endpoint, follow_redirects=False) as client:
            response = client.post(MCP_PATH, json={"jsonrpc": "2.0"})
        self.assertIn(response.status_code, (307, 308))

    def test_the_served_path_carries_the_separator_a_mount_requires(self):
        self.assertEqual(SERVED_PATH, f"{MCP_PATH}/")


class MetadataRedirectTest(unittest.TestCase):
    """The trailing-slash path and the bare prefix redirect to the document route."""

    def setUp(self):
        self.endpoint = built_endpoint(self)

    def test_the_trailing_slash_path_redirects_to_the_answering_route(self):
        with host_application(self.endpoint, follow_redirects=False) as client:
            response = client.get(f"{DOCUMENT_PATH}/")
        self.assertEqual(redirect_target(self, response), DOCUMENT_PATH)

    def test_the_bare_prefix_redirects_to_the_answering_route(self):
        with host_application(self.endpoint, follow_redirects=False) as client:
            response = client.get(PROTECTED_RESOURCE_PREFIX)
        self.assertEqual(redirect_target(self, response), DOCUMENT_PATH)

    def test_the_route_they_redirect_to_answers_rather_than_redirecting(self):
        # The redirect target returns the document directly.
        with host_application(self.endpoint, follow_redirects=False) as client:
            response = client.get(DOCUMENT_PATH)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response.headers["content-type"])

    def test_a_preflight_is_not_refused(self):
        # A browser sends an OPTIONS preflight first. A 405 stops the fetch.
        with host_application(self.endpoint, follow_redirects=False) as client:
            response = client.options(
                f"{DOCUMENT_PATH}/",
                headers={
                    "Origin": SERVICE_URL,
                    "Access-Control-Request-Method": "GET",
                },
            )
        self.assertNotEqual(response.status_code, 405)


class AmbiguousDocumentRouteTest(unittest.TestCase):
    """With zero or several document routes, no redirects are registered and nothing raises.

    The endpoint is built when the host module is imported, so raising here would stop the web
    interface from starting.
    """

    @staticmethod
    def _route(path):
        return Route(path, lambda request: PlainTextResponse(""), methods=["GET"])

    def test_no_document_route_registers_no_redirects(self):
        # The bare prefix is not a document route.
        routes = [self._route(PROTECTED_RESOURCE_PREFIX)]
        self.assertEqual(_metadata_redirect_routes(routes), [])

    def test_two_document_routes_register_no_redirects(self):
        routes = [
            self._route(DOCUMENT_PATH),
            self._route(f"{PROTECTED_RESOURCE_PREFIX}/other"),
        ]
        self.assertEqual(_metadata_redirect_routes(routes), [])

    def test_a_sibling_sharing_the_prefix_is_not_taken_for_the_document(self):
        # A prefix-only match would count this as a second document route.
        routes = [
            self._route(DOCUMENT_PATH),
            self._route(f"{PROTECTED_RESOURCE_PREFIX}-draft"),
        ]
        paths = [route.path for route in _metadata_redirect_routes(routes)]
        self.assertEqual(paths, [f"{DOCUMENT_PATH}/", PROTECTED_RESOURCE_PREFIX])

    def test_a_path_the_provider_answers_itself_is_not_shadowed(self):
        # When the provider already serves the bare prefix, no redirect is added for it.
        routes = [self._route(DOCUMENT_PATH), self._route(PROTECTED_RESOURCE_PREFIX)]
        paths = [route.path for route in _metadata_redirect_routes(routes)]
        self.assertEqual(paths, [f"{DOCUMENT_PATH}/"])


if __name__ == "__main__":
    unittest.main()
