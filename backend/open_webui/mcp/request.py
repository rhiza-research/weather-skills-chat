"""A synthetic Starlette request for calling catalog functions from the endpoint.

The catalog functions read application state from a request, and an MCP call has none. Both tool
listing and tool calls use this one builder. Modeled on the request the automation scheduler builds.
"""

from starlette.requests import Request

from open_webui.mcp.auth import MCP_PATH

# The header get_tools reads the active organization from. The interface sends the same header.
ORGANIZATION_HEADER = "X-Organization-Id"

# No credentials. The endpoint resolves the caller from its verified token before this is used.
_SCOPE_TEMPLATE = {
    "type": "http",
    "asgi": {"version": "3.0"},
    "http_version": "1.1",
    "method": "POST",
    "scheme": "http",
    "query_string": b"",
    "client": ("127.0.0.1", 0),
    "server": ("127.0.0.1", 80),
}


def core_request(app, organization_id: str) -> Request:
    """A request carrying `app`, with its path set to MCP_PATH.

    Its one header is ORGANIZATION_HEADER set to organization_id, so get_tools limits skills to the
    ones that organization enables.
    """
    scope = {
        **_SCOPE_TEMPLATE,
        "path": MCP_PATH,
        "raw_path": MCP_PATH.encode(),
        "headers": [(ORGANIZATION_HEADER.lower().encode(), organization_id.encode())],
        "app": app,
    }
    return Request(scope)
