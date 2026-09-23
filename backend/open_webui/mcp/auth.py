"""The endpoint's resource identifier and its authorization server.

The backend is the authorization server itself. Clients register, the user signs in through the
web interface and approves the client, and the issued tokens resolve to Open WebUI user ids.
"""

import logging
from urllib.parse import urlsplit

from open_webui.config import WEBUI_URL
from open_webui.mcp_oauth.provider import EndpointOAuthProvider, build_provider

log = logging.getLogger(__name__)

# The endpoint's path. Also the suffix of the resource identifier, which every access token must
# carry.
MCP_PATH = "/mcp"

CONFIGURED_MESSAGE = (
    "MCP endpoint enabled. Resource identifier %s, authorization server %s."
)

MISSING_BASE_URL_MESSAGE = (
    "WEBUI_URL is empty. The MCP endpoint uses WEBUI_URL as its resource identifier and as its "
    "authorization server's address. Set WEBUI_URL to this service's external address."
)


def _configured(setting) -> str:
    return str(setting.value or "").strip()


def service_url() -> str:
    """WEBUI_URL with no trailing slash: the authorization server's issuer and route origin."""
    base_url = _configured(WEBUI_URL).rstrip("/")
    if not base_url:
        raise RuntimeError(MISSING_BASE_URL_MESSAGE)
    return base_url


def canonical_resource_identifier() -> str:
    """WEBUI_URL plus MCP_PATH, with no trailing slash.

    Carried by every access token and advertised as the resource. RFC 9728 clients reject the
    metadata document if the advertised resource differs, including by a trailing slash.
    """
    return f"{service_url()}{MCP_PATH}"


def service_origin() -> str:
    """Scheme and authority of the resource identifier, for comparing with an Origin header."""
    parts = urlsplit(canonical_resource_identifier())
    return f"{parts.scheme}://{parts.netloc}"


def build_auth_provider() -> EndpointOAuthProvider:
    """Build the endpoint's authorization server. Makes no network call."""
    provider = build_provider(service_url(), canonical_resource_identifier())
    log.info(CONFIGURED_MESSAGE, provider.resource_identifier, provider.service_url)
    return provider
