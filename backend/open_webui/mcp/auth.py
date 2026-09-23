"""The MCP endpoint's resource identifier, and the call that builds its auth provider.

The endpoint authenticates requests with its own provider, separate from the interface's. An auth
implementation supplies the body of build_auth_provider.
"""

import logging

from fastmcp.server.auth import AuthProvider

from open_webui.config import WEBUI_URL

log = logging.getLogger(__name__)

# The endpoint's path. Also the suffix of the resource identifier.
MCP_PATH = "/mcp"

MISSING_BASE_URL_MESSAGE = (
    "WEBUI_URL is empty. The MCP endpoint uses WEBUI_URL as its resource identifier. Set WEBUI_URL "
    "to this service's external address."
)

NO_AUTH_IMPLEMENTATION_MESSAGE = (
    "No auth implementation supplies build_auth_provider. The MCP endpoint is always served and "
    "cannot be built without one."
)


def _configured(setting) -> str:
    return str(setting.value or "").strip()


def canonical_resource_identifier() -> str:
    """WEBUI_URL plus MCP_PATH, with no trailing slash.

    Advertised as the resource. RFC 9728 clients reject the metadata document if the advertised
    resource differs, including by a trailing slash. Raises when WEBUI_URL is empty.
    """
    base_url = _configured(WEBUI_URL).rstrip("/")
    if not base_url:
        raise RuntimeError(MISSING_BASE_URL_MESSAGE)
    return f"{base_url}{MCP_PATH}"


def build_auth_provider() -> AuthProvider:
    """Build the provider the endpoint's FastMCP server authenticates requests with.

    An auth implementation supplies this body. The provider it returns verifies bearer tokens,
    answers a request without a valid token with the 401 challenge, and serves the protected
    resource metadata for canonical_resource_identifier(). It makes no network call. It raises
    when its configuration is missing or invalid, because the endpoint is always served and
    startup stops on that error.
    """
    raise NotImplementedError(NO_AUTH_IMPLEMENTATION_MESSAGE)
