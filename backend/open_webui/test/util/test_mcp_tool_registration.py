"""Tool listing and tool calls, answered from the calling account's catalog on each request.

Listing does not create a session. A call resolves the account's session before it runs. Both use
the organization the request names.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastmcp.exceptions import ToolError

from open_webui.mcp.tools import AccountCatalogMiddleware

ACCOUNT = SimpleNamespace(
    id="account-1", email="priya@example.com", name="Priya", role="user"
)
APP = SimpleNamespace(state=SimpleNamespace(TOOLS={}))
SESSION_ID = "b2c3d4e5-0000-4000-8000-000000000000"
SESSION = SimpleNamespace(id=SESSION_ID, user_id=ACCOUNT.id, chat={"history": {}})
ORG = "org-1"

RAIN_SPEC = {
    "name": "fetch_rain",
    "description": "Fetch rainfall",
    "parameters": {"type": "object", "properties": {"bbox": {"type": "string"}}},
}


def entry(callable_=None, spec=RAIN_SPEC):
    return {"spec": spec, "callable": callable_ or AsyncMock(return_value={"ok": True})}


def message(name, arguments=None):
    return SimpleNamespace(
        message=SimpleNamespace(name=name, arguments=arguments or {})
    )


class ListToolsTest(unittest.IsolatedAsyncioTestCase):
    async def listed(self, entries):
        middleware = AccountCatalogMiddleware(APP)
        with patch(
            "open_webui.mcp.tools.resolve_caller", return_value=ACCOUNT
        ), patch(
            "open_webui.mcp.tools.call_organization_id", return_value=ORG
        ), patch(
            "open_webui.mcp.tools.endpoint_catalog", return_value=entries
        ), patch(
            "open_webui.mcp.tools.owned_session"
        ) as session:
            tools = await middleware.on_list_tools(message("ignored"), AsyncMock())
        return tools, session

    async def test_one_descriptor_per_published_entry(self):
        tools, _ = await self.listed({"fetch_rain": entry(), "list_artifacts": entry()})
        self.assertEqual(sorted(t.name for t in tools), ["fetch_rain", "list_artifacts"])

    async def test_the_catalog_key_is_the_name_a_caller_invokes(self):
        # After a name collision is resolved, the catalog key differs from the spec's name.
        tools, _ = await self.listed({"fetch_rain_v2": entry()})
        self.assertEqual(tools[0].name, "fetch_rain_v2")

    async def test_the_derived_description_and_schema_travel(self):
        tools, _ = await self.listed({"fetch_rain": entry()})
        self.assertEqual(tools[0].description, "Fetch rainfall")
        self.assertIn("bbox", tools[0].parameters["properties"])

    async def test_a_spec_without_a_description_falls_back_to_the_name(self):
        tools, _ = await self.listed({"bare": entry(spec={})})
        self.assertEqual(tools[0].description, "bare")

    async def test_listing_creates_no_session(self):
        _, session = await self.listed({"fetch_rain": entry()})
        session.assert_not_called()

    async def test_an_empty_catalog_lists_nothing(self):
        tools, _ = await self.listed({})
        self.assertEqual(tools, [])


class CallToolTest(unittest.IsolatedAsyncioTestCase):
    async def call(self, entries, name, arguments=None):
        middleware = AccountCatalogMiddleware(APP)
        with patch(
            "open_webui.mcp.tools.resolve_caller", return_value=ACCOUNT
        ), patch(
            "open_webui.mcp.tools.call_organization_id", return_value=ORG
        ), patch(
            "open_webui.mcp.tools.endpoint_catalog", return_value=entries
        ), patch(
            "open_webui.mcp.tools.owned_session", return_value=SESSION
        ), patch(
            "open_webui.mcp.tools.record_tool_call"
        ) as recorded, patch(
            "open_webui.mcp.tools.run_context", return_value={}
        ) as context:
            result = await middleware.on_call_tool(
                message(name, arguments), AsyncMock()
            )
        return result, context, recorded

    async def test_a_call_reaches_the_entry_callable(self):
        target = AsyncMock(return_value={"ok": True, "stdout": "done"})
        result, _, recorded = await self.call(
            {"fetch_rain": entry(target)}, "fetch_rain"
        )
        target.assert_awaited_once()
        recorded.assert_called_once()
        self.assertEqual(result.structured_content["stdout"], "done")

    async def test_arguments_are_passed_through(self):
        target = AsyncMock(return_value={"ok": True})
        await self.call({"fetch_rain": entry(target)}, "fetch_rain", {"bbox": "0,0,1,1"})
        target.assert_awaited_once_with(bbox="0,0,1,1")

    async def test_context_parameter_names_from_the_caller_are_dropped(self):
        # The callable binds __user__ and __metadata__; a caller must not replace them.
        target = AsyncMock(return_value={"ok": True})
        await self.call(
            {"fetch_rain": entry(target)},
            "fetch_rain",
            {
                "bbox": "0,0,1,1",
                "__user__": {"id": "someone-else"},
                "__metadata__": {"chat_id": "another-chat", "organization_id": "org-2"},
                "__id__": "another-tool",
            },
        )
        target.assert_awaited_once_with(bbox="0,0,1,1")

    async def test_the_recorded_arguments_leave_out_context_parameter_names(self):
        _, _, recorded = await self.call(
            {"fetch_rain": entry()},
            "fetch_rain",
            {"bbox": "0,0,1,1", "__metadata__": {"chat_id": "another-chat"}},
        )
        self.assertEqual(recorded.call_args.kwargs["arguments"], {"bbox": "0,0,1,1"})

    async def test_a_call_resolves_a_session_first(self):
        _, context, _recorded = await self.call(
            {"fetch_rain": entry()}, "fetch_rain"
        )
        self.assertEqual(context.call_args.args[1], SESSION_ID)

    async def test_an_unpublished_name_is_refused(self):
        with self.assertRaises(ToolError):
            await self.call({"fetch_rain": entry()}, "create_preference")

    async def test_a_failed_run_is_a_readable_result_not_a_raise(self):
        # The runner reports failure in its return value. The result keeps stderr and sets is_error.
        target = AsyncMock(return_value={"ok": False, "stderr": "boom", "exit_code": 1})
        result, _, _recorded = await self.call(
            {"fetch_rain": entry(target)}, "fetch_rain"
        )
        self.assertTrue(result.is_error)
        self.assertEqual(result.structured_content["stderr"], "boom")

    async def test_a_successful_run_is_not_flagged_as_an_error(self):
        target = AsyncMock(return_value={"ok": True})
        result, _, _recorded = await self.call(
            {"fetch_rain": entry(target)}, "fetch_rain"
        )
        self.assertFalse(result.is_error)

    async def test_a_string_returning_tool_comes_back_as_content(self):
        target = AsyncMock(return_value="two artifacts")
        result, _, _recorded = await self.call(
            {"list_artifacts": entry(target)}, "list_artifacts"
        )
        self.assertIsNone(result.structured_content)


class OrganizationTest(unittest.IsolatedAsyncioTestCase):
    """The organization the request names scopes the catalog, the session and the run."""

    def patches(self, refused=None):
        target = AsyncMock(return_value={"ok": True})
        self.target = target
        mocks = {}
        stack = [
            ("resolve_caller", {"return_value": ACCOUNT}),
            (
                "call_organization_id",
                {"side_effect": refused} if refused else {"return_value": ORG},
            ),
            ("endpoint_catalog", {"return_value": {"fetch_rain": entry(target)}}),
            ("owned_session", {"return_value": SESSION}),
            ("record_tool_call", {}),
            ("run_context", {"return_value": {}}),
        ]
        for name, kwargs in stack:
            started = patch(f"open_webui.mcp.tools.{name}", **kwargs)
            mocks[name] = started.start()
            self.addCleanup(started.stop)
        return mocks

    async def test_listing_builds_the_catalog_in_the_named_organization(self):
        mocks = self.patches()
        await AccountCatalogMiddleware(APP).on_list_tools(message("ignored"), AsyncMock())
        mocks["call_organization_id"].assert_called_once_with(ACCOUNT)
        self.assertEqual(mocks["endpoint_catalog"].call_args.args[2], ORG)

    async def test_a_call_uses_the_session_catalog_and_run_of_the_named_organization(self):
        mocks = self.patches()
        await AccountCatalogMiddleware(APP).on_call_tool(
            message("fetch_rain"), AsyncMock()
        )
        mocks["owned_session"].assert_called_once_with(ACCOUNT, ORG)
        self.assertEqual(mocks["endpoint_catalog"].call_args.args[2], ORG)
        self.assertEqual(mocks["run_context"].call_args.args[2], ORG)

    async def test_a_refused_organization_lists_nothing(self):
        mocks = self.patches(refused=ToolError("not a member"))
        with self.assertRaises(ToolError):
            await AccountCatalogMiddleware(APP).on_list_tools(
                message("ignored"), AsyncMock()
            )
        mocks["endpoint_catalog"].assert_not_called()

    async def test_a_refused_organization_runs_nothing_and_creates_no_session(self):
        mocks = self.patches(refused=ToolError("not a member"))
        with self.assertRaises(ToolError):
            await AccountCatalogMiddleware(APP).on_call_tool(
                message("fetch_rain"), AsyncMock()
            )
        mocks["owned_session"].assert_not_called()
        self.target.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
