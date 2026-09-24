"""A stub auth provider for tests of the endpoint that do not depend on an auth implementation.

The stub is fastmcp's RemoteAuthProvider with a token verifier that accepts one fixed token as a
fixed user id's token and refuses every other token. The provider answers a request without a
valid token with the 401 challenge and serves the protected resource metadata, as an auth
implementation's provider does.
"""

from contextlib import contextmanager
from unittest.mock import patch

from fastmcp.server.auth import AccessToken, RemoteAuthProvider, TokenVerifier
from pydantic import AnyHttpUrl

from open_webui.mcp.auth import canonical_resource_identifier

STUB_AUTHORIZATION_SERVER = "https://authorization.example"
STUB_TOKEN = "stub-token"
STUB_USER_ID = "stub-user-id"


class StubTokenVerifier(TokenVerifier):
    """Accepts STUB_TOKEN as STUB_USER_ID's token and refuses every other token."""

    async def verify_token(self, token: str) -> AccessToken | None:
        if token != STUB_TOKEN:
            return None
        return AccessToken(
            token=token, client_id="stub-client", scopes=[], subject=STUB_USER_ID
        )


def stub_auth_provider() -> RemoteAuthProvider:
    """A provider for the current WEBUI_URL. Raises, as build_auth_provider does, when it is empty."""
    return RemoteAuthProvider(
        token_verifier=StubTokenVerifier(),
        authorization_servers=[AnyHttpUrl(STUB_AUTHORIZATION_SERVER)],
        base_url=canonical_resource_identifier(),
    )


@contextmanager
def stub_auth():
    """Replace build_auth_provider, as the endpoint calls it, with stub_auth_provider."""
    with patch("open_webui.mcp.build_auth_provider", side_effect=stub_auth_provider):
        yield
