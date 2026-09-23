"""The MCP endpoint. It uses the same tool catalog, skill runner and artifact store as the chat loop."""

import logging
from typing import Any, NamedTuple

from fastmcp import FastMCP
from starlette.routing import Route

from open_webui.mcp.auth import (
    MCP_PATH,
    build_auth_provider,
)

log = logging.getLogger(__name__)

SERVER_NAME = "Weather Skills"

__all__ = [
    "MCP_PATH",
    "Endpoint",
    "build_endpoint",
]


class Endpoint(NamedTuple):
    """What the host application registers: the mount and the root-level routes.

    The discovery routes are registered at the host application's root because clients fetch them
    at root-absolute paths, which a route inside a mount cannot answer.
    """

    mount_path: str
    # FastMCP's HTTP app. The host and the tests call `asgi_app.lifespan(app)` as an async context
    # manager to start the Streamable HTTP session manager; a plain Starlette app has no such
    # attribute.
    asgi_app: Any
    root_routes: list[Route]


def build_endpoint() -> Endpoint:
    """Build the endpoint. The endpoint is always served.

    Raises when build_auth_provider raises, which it does for a missing or invalid configuration.

    The caller must run the returned app's lifespan: Starlette does not run a mounted app's lifespan,
    and the lifespan starts the session manager.
    """
    provider = build_auth_provider()
    server = FastMCP(name=SERVER_NAME, auth=provider)
    # path="/" serves the endpoint at the mount point instead of a nested /mcp/mcp.
    asgi_app = server.http_app(path="/")

    root_routes: list[Route] = []
    return Endpoint(mount_path=MCP_PATH, asgi_app=asgi_app, root_routes=root_routes)
