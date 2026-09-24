"""Token verification for the MCP endpoint, separate from the interface's.

The interface's tokens are HS256, carry no audience, and its decode raises on any token that has an
audience, so its verifier cannot check the endpoint's audience.
"""

import logging
import os
from urllib.parse import urlsplit

from fastmcp.server.auth.providers.jwt import JWTVerifier
from fastmcp.server.auth.providers.keycloak import KeycloakAuthProvider

from open_webui.config import OPENID_PROVIDER_URL, WEBUI_URL

log = logging.getLogger(__name__)

# The endpoint's path. Also the suffix of the resource identifier, which is the required token
# audience.
MCP_PATH = "/mcp"

# The realm URL is OPENID_PROVIDER_URL with this suffix removed.
OIDC_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"

# Optional. The realm URL clients use, when it differs from the realm URL this service reaches.
# Tokens must carry it as their issuer, and the metadata advertises it as the authorization server.
# Signing keys are still fetched from the realm derived from OPENID_PROVIDER_URL. Unset, both are
# that realm.
PUBLIC_REALM_URL_ENV = "MCP_PUBLIC_REALM_URL"

# Keycloak's signing-key path under a realm URL.
JWKS_PATH = "/protocol/openid-connect/certs"

CONFIGURED_MESSAGE = (
    "MCP endpoint enabled. Resource identifier %s, realm %s. Clients get tokens from the realm; "
    "this service only verifies them."
)

MISSING_BASE_URL_MESSAGE = (
    "WEBUI_URL is empty. The MCP endpoint uses WEBUI_URL as the token audience. Set WEBUI_URL "
    "to this service's external address."
)

UNSET_PROVIDER_URL_MESSAGE = (
    "OPENID_PROVIDER_URL is unset. The MCP endpoint verifies tokens against the OpenID provider "
    "it names. Set it to the provider's OpenID discovery URL, ending in "
    f"{OIDC_DISCOVERY_SUFFIX!r}."
)

MALFORMED_PROVIDER_URL_MESSAGE = (
    "OPENID_PROVIDER_URL must be an OpenID discovery URL ending in "
    f"{OIDC_DISCOVERY_SUFFIX!r}. Got {{value!r}}."
)


def _configured(setting) -> str:
    return str(setting.value or "").strip()


def canonical_resource_identifier() -> str:
    """WEBUI_URL plus MCP_PATH, with no trailing slash.

    Used as the token audience and as the advertised resource. RFC 9728 clients reject the
    metadata document if the advertised resource differs, including by a trailing slash.
    """
    base_url = _configured(WEBUI_URL).rstrip("/")
    if not base_url:
        raise RuntimeError(MISSING_BASE_URL_MESSAGE)
    return f"{base_url}{MCP_PATH}"


def realm_url() -> str:
    """The realm URL: OPENID_PROVIDER_URL without the discovery suffix.

    Raises when OPENID_PROVIDER_URL is unset or is not a discovery URL. The endpoint is always
    served, so startup stops on that error.
    """
    provider_url = _configured(OPENID_PROVIDER_URL).rstrip("/")
    if not provider_url:
        raise RuntimeError(UNSET_PROVIDER_URL_MESSAGE)
    if not provider_url.endswith(OIDC_DISCOVERY_SUFFIX):
        raise RuntimeError(
            MALFORMED_PROVIDER_URL_MESSAGE.format(value=provider_url)
        )
    return provider_url[: -len(OIDC_DISCOVERY_SUFFIX)]


def public_realm_url() -> str:
    """The realm URL clients use: MCP_PUBLIC_REALM_URL if set, otherwise realm_url()."""
    public = os.environ.get(PUBLIC_REALM_URL_ENV, "").strip().rstrip("/")
    return public or realm_url()


def service_origin() -> str:
    """Scheme and authority of the resource identifier, for comparing with an Origin header."""
    parts = urlsplit(canonical_resource_identifier())
    return f"{parts.scheme}://{parts.netloc}"


class NoAdvertisedScopesProvider(KeycloakAuthProvider):
    """KeycloakAuthProvider without scopes_supported in the protected resource metadata.

    The field is optional under RFC 9728. A client that copies the advertised scopes into its
    dynamic client registration is limited to those scopes, and Keycloak then refuses its
    authorization request with invalid_scope. Without the field, the client registers with no
    scopes and Keycloak accepts it.

    Verification still requires the verifier's required_scopes, and the 401 challenge still names
    them through get_challenge_scopes. Tests cover both.

    KeycloakAuthProvider has no argument that omits the field: None falls back to the verifier's
    scopes and an empty list is published as an empty list. Overriding this property returns None,
    which the metadata model accepts because the field is optional.
    """

    @property
    def scopes_supported(self) -> list[str] | None:
        return None


def build_auth_provider() -> KeycloakAuthProvider:
    """Build the endpoint's verifier.

    The server returns 401 and serves the metadata routes only when given a provider. No network
    call is made here: the JWKS URI is built from the realm URL and keys are fetched on first use,
    so the process starts even when the identity provider is down.

    The advertised authorization server and the required issuer are public_realm_url(). Keys are
    fetched from realm_url().

    Only the openid scope is required. Tokens from a browser sign-in carry only that scope.
    """
    resource_identifier = canonical_resource_identifier()
    public_realm = public_realm_url()
    verifier = JWTVerifier(
        jwks_uri=f"{realm_url()}{JWKS_PATH}",
        issuer=public_realm,
        algorithm="RS256",
        required_scopes=["openid"],
        # The verifier checks the audience only when audience is truthy.
        audience=resource_identifier,
    )
    provider = NoAdvertisedScopesProvider(
        realm_url=public_realm,
        base_url=resource_identifier,
        token_verifier=verifier,
    )
    log.info(CONFIGURED_MESSAGE, resource_identifier, public_realm)
    return provider
