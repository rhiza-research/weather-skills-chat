"""A test host that registers the endpoint in the same order as the real application.

The mounted endpoint writes the auth challenge, and a root route on the host serves the discovery
document. Those root routes must be registered before the mount that serves the web interface. A
test app built from the endpoint's routes alone cannot check that ordering.
"""

from contextlib import asynccontextmanager, contextmanager

from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Mount
from starlette.testclient import TestClient

INTERFACE_BODY = "<!doctype html><title>the web interface</title>"

# The service address the endpoint tests configure. https, because the MCP SDK refuses a plain
# http issuer unless its host is a loopback name.
SERVICE_URL = "https://chat.example"


@contextmanager
def service_configured(base_url=SERVICE_URL):
    """Set WEBUI_URL, which the endpoint reads, then restore it.

    unittest.mock cannot patch it: it reads the target's __dict__, and PersistentConfig raises
    TypeError for __dict__.
    """
    from open_webui.config import WEBUI_URL

    previous = WEBUI_URL.value
    WEBUI_URL.value = base_url
    try:
        yield
    finally:
        WEBUI_URL.value = previous


class InterfaceStandIn:
    """Answers any path with an HTML 200, like the frontend's fallback route.

    Mounted at the root and registered last. A root mount matches every path not claimed by an
    earlier route, and Starlette's trailing-slash redirect does not run behind it. If the endpoint's
    routes were registered after it, a client following the auth challenge would get a web page
    with status 200.
    """

    async def __call__(self, scope, receive, send):
        await HTMLResponse(INTERFACE_BODY)(scope, receive, send)


def host_routes(endpoint):
    """The endpoint's root routes, its mount, and the interface stand-in, in the host's order."""
    return [
        *endpoint.root_routes,
        Mount(endpoint.mount_path, endpoint.asgi_app),
        Mount("/", app=InterfaceStandIn()),
    ]


@contextmanager
def host_application(endpoint, follow_redirects=True):
    """A test client over the host application, with the mounted endpoint's lifespan running.

    Starlette does not run a mounted app's lifespan, so the host runs it, as the real host does.
    The lifespan starts the transport's session manager.
    """

    @asynccontextmanager
    async def lifespan(app):
        async with endpoint.asgi_app.lifespan(app):
            yield

    app = Starlette(routes=host_routes(endpoint), lifespan=lifespan)
    with TestClient(app, follow_redirects=follow_redirects) as client:
        yield client
