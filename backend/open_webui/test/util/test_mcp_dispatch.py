"""FastMCP's dispatch calls the endpoint's middleware hooks, and main.py registers routes in order.

The other tests call the middleware methods directly. These tests go through the library's client,
so a renamed hook or a changed hook signature fails here. The route order is read from main.py,
because a test that builds its own application only sees the order it chose.
"""

import ast
import asyncio
import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastmcp import Client, FastMCP

import open_webui
from open_webui.mcp import tools as endpoint_tools
from open_webui.mcp.tools import AccountCatalogMiddleware

ACCOUNT = SimpleNamespace(id="an-account", role="user")
SESSION = SimpleNamespace(id="a-session")
HOST_APP = SimpleNamespace(state=SimpleNamespace(TOOLS={}))

TOOL_NAME = "a_published_tool"
TOOL_SPEC = {
    "name": TOOL_NAME,
    "description": "A tool the account publishes.",
    "parameters": {
        "type": "object",
        "properties": {"who": {"type": "string"}},
        "required": [],
    },
}


async def _callable(**arguments):
    return {"ok": True, "stdout": f"called with {sorted(arguments)}"}


CATALOG = {TOOL_NAME: {"spec": TOOL_SPEC, "callable": _callable}}


class LibraryDispatchTest(unittest.TestCase):
    """Listing and calling go through the FastMCP client into the middleware.

    The server has no auth provider and the caller is stubbed. Authentication is tested with the
    auth implementation that supplies the provider.
    """

    def setUp(self):
        self.server = FastMCP(name="dispatch-test")
        self.server.add_middleware(AccountCatalogMiddleware(HOST_APP))
        self.patches = [
            patch.object(endpoint_tools, "resolve_caller", return_value=ACCOUNT),
            patch.object(endpoint_tools, "call_organization_id", return_value="an-org"),
            patch.object(endpoint_tools, "owned_session", return_value=SESSION),
            patch.object(endpoint_tools, "endpoint_catalog", return_value=CATALOG),
            patch.object(endpoint_tools, "record_tool_call"),
            patch.object(endpoint_tools, "caller_only_context", return_value={}),
            patch.object(endpoint_tools, "run_context", return_value={}),
        ]
        for started in self.patches:
            started.start()
            self.addCleanup(started.stop)

    def _run(self, coroutine_factory):
        async def go():
            async with Client(self.server) as client:
                return await coroutine_factory(client)

        return asyncio.run(go())

    def test_listing_reaches_the_endpoint_and_returns_its_catalog(self):
        listed = self._run(lambda client: client.list_tools())
        self.assertEqual([tool.name for tool in listed], [TOOL_NAME])

    def test_the_listed_tool_carries_the_catalog_entry_description(self):
        listed = self._run(lambda client: client.list_tools())
        self.assertEqual(listed[0].description, TOOL_SPEC["description"])

    def test_calling_reaches_the_endpoint_and_returns_the_value(self):
        result = self._run(
            lambda client: client.call_tool(TOOL_NAME, {"who": "a-caller"})
        )
        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content.get("ok"), True)

    def test_an_unpublished_name_is_refused_through_the_same_path(self):
        from fastmcp.exceptions import ToolError

        with self.assertRaises(ToolError):
            self._run(lambda client: client.call_tool("not_published", {}))


class RegistrationOrderTest(unittest.TestCase):
    """The endpoint's routes are registered before the mount that serves the interface.

    Registration order in main.py is source order, and nothing reorders `app.router.routes` after
    startup, so the test compares line numbers in main.py.
    """

    @classmethod
    def setUpClass(cls):
        # Read by path, because importing main.py builds the application and runs migrations.
        host = pathlib.Path(open_webui.__file__).parent / "main.py"
        cls.source = host.read_text()
        cls.tree = ast.parse(cls.source)

    def _lines_calling(self, predicate):
        found = []
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and predicate(ast.unparse(node)):
                found.append(node.lineno)
        return sorted(found)

    def test_the_endpoint_routes_are_registered(self):
        self.assertTrue(self._lines_calling(lambda s: "root_routes" in s))

    def test_the_interface_catch_all_is_mounted(self):
        self.assertTrue(
            self._lines_calling(
                lambda s: s.startswith("app.mount(") and "SPAStaticFiles" in s
            )
        )

    def test_discovery_and_the_endpoint_precede_the_catch_all(self):
        catch_all = min(
            self._lines_calling(
                lambda s: s.startswith("app.mount(") and "SPAStaticFiles" in s
            )
        )
        for description, predicate in (
            ("the discovery routes", lambda s: "root_routes" in s),
            (
                "the endpoint mount",
                lambda s: s.startswith("app.mount(") and "mcp_endpoint" in s,
            ),
        ):
            lines = self._lines_calling(predicate)
            self.assertTrue(lines, f"{description} is not registered at all")
            self.assertLess(
                max(lines),
                catch_all,
                f"{description} is registered after the interface's catch-all mount, "
                "which matches every path",
            )


if __name__ == "__main__":
    unittest.main()
