"""MCP middleware that answers tools/list and tools/call from the caller's own catalog.

The catalog depends on the account and the organization the request names, so it is built per
request instead of registered at startup. Listing builds it without a session; calling creates or
finds the account's session in that organization first.
"""

import logging

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from fastmcp.tools import Tool, ToolResult

from open_webui.mcp.catalog import endpoint_catalog
from open_webui.mcp.identity import resolve_caller
from open_webui.mcp.organization import call_organization_id
from open_webui.mcp.run import caller_only_context, run_context
from open_webui.mcp.session import owned_session
from open_webui.mcp.transcript import record_tool_call

log = logging.getLogger(__name__)

EMPTY_PARAMETERS = {"type": "object", "properties": {}}

UNKNOWN_TOOL_MESSAGE = (
    "No tool named {name!r} is available to this account. List the tools again; the list changes "
    "when a skill is installed, updated or removed."
)


def _descriptor(name: str, entry: dict) -> Tool:
    """A catalog entry as an MCP Tool.

    Uses the catalog key as the name, which can differ from the spec's name after a name collision.
    """
    spec = entry.get("spec") or {}
    return Tool(
        name=name,
        description=spec.get("description") or name,
        parameters=spec.get("parameters") or EMPTY_PARAMETERS,
    )


def _reports_failure(returned) -> bool:
    """Whether a tool's return value reports failure.

    True for a dict with ok=False, a non-empty error, or a nonzero integer exit_code, and for an
    exception instance.
    """
    if isinstance(returned, dict):
        if returned.get("ok") is False:
            return True
        if returned.get("error"):
            return True
        exit_code = returned.get("exit_code")
        return isinstance(exit_code, int) and exit_code != 0
    return isinstance(returned, BaseException)


def _as_result(returned) -> ToolResult:
    """A tool's return value as a ToolResult.

    A failed run is returned as a normal result with is_error set, not as a protocol error.
    """
    is_error = _reports_failure(returned)
    if isinstance(returned, dict):
        return ToolResult(structured_content=returned, is_error=is_error)
    return ToolResult(content=returned, is_error=is_error)


def _caller_arguments(arguments) -> dict:
    """The call's arguments without names starting with "__".

    Those names are the context parameters the endpoint binds, such as __user__ and __metadata__.
    A caller passing one would replace the bound value with its own account, session or
    organization.
    """
    return {
        name: value
        for name, value in (arguments or {}).items()
        if not name.startswith("__")
    }


class AccountCatalogMiddleware(Middleware):
    """Answers tools/list and tools/call from the calling account's catalog."""

    def __init__(self, app):
        # The host application; catalog functions read its state.
        self._app = app

    async def on_list_tools(self, context, call_next):
        account = resolve_caller()
        organization_id = call_organization_id(account)
        entries = endpoint_catalog(
            self._app, account, organization_id, caller_only_context(account)
        )
        log.debug("Listing %d tools for %s", len(entries), account.id)
        return [_descriptor(name, entry) for name, entry in entries.items()]

    async def on_call_tool(self, context, call_next):
        account = resolve_caller()
        organization_id = call_organization_id(account)
        # The session is resolved before the tool runs, so the run has its own directory.
        session = owned_session(account, organization_id)
        entries = endpoint_catalog(
            self._app,
            account,
            organization_id,
            run_context(account, session.id, organization_id),
        )
        name = context.message.name
        entry = entries.get(name)
        if entry is None:
            raise ToolError(UNKNOWN_TOOL_MESSAGE.format(name=name))
        arguments = _caller_arguments(context.message.arguments)
        returned = await entry["callable"](**arguments)
        # Records the call after it completes. record_tool_call does not raise.
        record_tool_call(session, name=name, arguments=arguments, result=returned)
        return _as_result(returned)
