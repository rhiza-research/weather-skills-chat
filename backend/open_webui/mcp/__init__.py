"""The MCP endpoint. It uses the same tool catalog, skill runner and artifact store as the chat loop."""

import logging
from typing import Any, NamedTuple

from fastmcp import FastMCP
from mcp.server.auth.routes import cors_middleware
from starlette.responses import RedirectResponse
from starlette.routing import Route

from open_webui.mcp.auth import (
    MCP_PATH,
    build_auth_provider,
    service_origin,
)

log = logging.getLogger(__name__)

SERVER_NAME = "Weather Skills"

# A Starlette mount matches only paths with a separator after the prefix, so the endpoint is served
# at MCP_PATH plus a trailing slash. The bare MCP_PATH redirects here; without that redirect the
# frontend route answers it with an HTML page and status 200.
SERVED_PATH = f"{MCP_PATH}/"

# RFC 9728 path prefix for protected resource metadata.
PROTECTED_RESOURCE_PREFIX = "/.well-known/oauth-protected-resource"

# 308 keeps the request method and body on redirect.
REDIRECT_STATUS = 308

# OPTIONS is included so a browser CORS preflight gets an answer instead of 405.
REDIRECT_METHODS = ["GET", "POST", "DELETE", "HEAD", "OPTIONS"]

AMBIGUOUS_METADATA_MESSAGE = (
    "Not registering the metadata redirects: found %d routes under %s, expected exactly one. "
    "Paths: %s. The provider's own metadata route is still registered; the trailing-slash and "
    "bare-prefix paths are not redirected to it."
)

__all__ = [
    "MCP_PATH",
    "PROTECTED_RESOURCE_PREFIX",
    "REDIRECT_METHODS",
    "REDIRECT_STATUS",
    "SERVED_PATH",
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


async def _redirect_to_served_path(request):
    return RedirectResponse(SERVED_PATH, status_code=REDIRECT_STATUS)


def _redirect_to(target: str):
    async def redirect(request):
        return RedirectResponse(target, status_code=REDIRECT_STATUS)

    return redirect


def _redirect_route(path: str, target: str, name: str) -> Route:
    """A redirect route with the same CORS wrapper the library puts on the metadata route."""
    return Route(
        path,
        cors_middleware(_redirect_to(target), REDIRECT_METHODS),
        methods=REDIRECT_METHODS,
        name=name,
    )


def _document_route_paths(well_known_routes: list[Route]) -> list[str]:
    """The registered paths that serve a protected resource metadata document.

    Matches the prefix followed by "/", so the bare prefix and paths that only share leading
    characters are excluded.
    """
    return [
        route.path
        for route in well_known_routes
        if route.path.startswith(f"{PROTECTED_RESOURCE_PREFIX}/")
    ]


def _metadata_redirect_routes(well_known_routes: list[Route]) -> list[Route]:
    """Redirects from two more metadata paths to the provider's metadata route.

    The transport's WWW-Authenticate challenge names the metadata URL with a trailing slash, because
    the server is mounted at "/" inside its own app. Clients that get no document there retry at the
    bare prefix. Without these redirects both paths reach the frontend route, which returns HTML
    with status 200.

    The bare-prefix redirect leads to a document whose resource identifier includes the endpoint
    path, so a client asking about the origin-level resource rejects it under RFC 9728.

    The redirect target is taken from the provider's registered routes. If there is not exactly one
    metadata route, this logs an error and returns no redirects. It does not raise, because the
    endpoint is built at import time of the host module and raising would stop the web interface.
    """
    document_paths = _document_route_paths(well_known_routes)
    if len(document_paths) != 1:
        log.error(
            AMBIGUOUS_METADATA_MESSAGE,
            len(document_paths),
            PROTECTED_RESOURCE_PREFIX,
            document_paths,
        )
        return []
    document_path = document_paths[0]
    already_registered = {route.path for route in well_known_routes}
    return [
        _redirect_route(path, document_path, name)
        for path, name in (
            (f"{document_path}/", "mcp-metadata-trailing-slash"),
            (PROTECTED_RESOURCE_PREFIX, "mcp-metadata-prefix"),
        )
        # Skip paths the provider already serves and paths equal to the target, which would shadow
        # the document or loop.
        if path != document_path and path not in already_registered
    ]


def build_endpoint() -> Endpoint:
    """Build the endpoint. The endpoint is always served.

    Raises when build_auth_provider raises, which it does for a missing or invalid configuration.

    The caller must run the returned app's lifespan: Starlette does not run a mounted app's lifespan,
    and the lifespan starts the session manager.
    """
    provider = build_auth_provider()
    server = FastMCP(name=SERVER_NAME, auth=provider)
    # path="/" serves the endpoint at the mount point instead of a nested /mcp/mcp.
    #
    # Origin protection defaults to off. "auto" with an explicit origin checks the Origin header
    # when present and does not check Host: requests without Origin (agents) pass, and browser
    # requests from another origin are refused. This does not depend on the interface's CORS
    # middleware settings.
    asgi_app = server.http_app(
        path="/",
        host_origin_protection="auto",
        allowed_origins=[service_origin()],
    )

    root_routes: list[Route] = [
        Route(
            MCP_PATH,
            _redirect_to_served_path,
            methods=REDIRECT_METHODS,
            name="mcp-bare-path",
        )
    ]
    # No mcp_path argument: the provider derives the resource path from base_url, which includes
    # MCP_PATH. Passing it again registers /.well-known/oauth-protected-resource/mcp/mcp.
    well_known_routes = provider.get_well_known_routes()
    root_routes.extend(well_known_routes)
    root_routes.extend(_metadata_redirect_routes(well_known_routes))
    return Endpoint(mount_path=MCP_PATH, asgi_app=asgi_app, root_routes=root_routes)
