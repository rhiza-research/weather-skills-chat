"""The authorization server's protocol methods, backed by the database.

fastmcp's OAuthProvider routes the MCP SDK's metadata, authorize, token, register and revoke
handlers to the methods here. The SDK checks PKCE, the redirect URI match at the token endpoint,
and the expiry fields it is given. It does not validate the resource indicator, consume codes, or
check redirect URIs at registration, so those are done here.

Clients are identified in one of two ways:

- A Client ID Metadata Document: the client_id is an https URL, and the document fetched from it
  (through fastmcp's SSRF-protected fetcher) lists the client's name and redirect URIs.
- Dynamic Client Registration: the SDK generates a client_id and the client's metadata is stored.
  Only public clients (token_endpoint_auth_method "none") can register. The SDK's client
  authenticator compares a presented client secret with the stored plaintext, so a secret could
  not be stored as a hash without replacing that SDK code, and plaintext secrets are not stored.

Tokens are opaque random values. The database holds only their SHA-256 digests.
"""

import asyncio
import logging
import os
import secrets
import time
from typing import Iterable, Optional
from urllib.parse import SplitResult, unquote, urlencode, urlsplit

from fastmcp.server.auth.auth import (
    AccessToken,
    OAuthProvider,
    PrivateKeyJWTClientAuthenticator,
    TokenHandler,
)
from fastmcp.server.auth.cimd import (
    CIMDClientManager,
    CIMDDocument,
    CIMDFetcher,
    CIMDFetchError,
    CIMDValidationError,
)
from fastmcp.server.auth.redirect_validation import matches_allowed_pattern
from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.handlers.metadata import MetadataHandler
from mcp.server.auth.middleware.client_auth import AuthenticationError
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.routes import build_metadata, cors_middleware
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import (
    DEFAULT_MAX_REQUEST_BODY_SIZE,
    RequestBodyLimitMiddleware,
)
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken
from mcp.shared.inbound import MCP_PROTOCOL_VERSION_HEADER
from pydantic import AnyUrl, Field
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, request_response

from open_webui.mcp_oauth.accounts import active_account
from open_webui.models.mcp_oauth import (
    ACCESS,
    REFRESH,
    AuthorizationRecord,
    ClientExistsError,
    McpOAuth,
    McpOAuthTable,
)

log = logging.getLogger(__name__)

# Comma-separated redirect URIs a client may use besides loopback http. Each entry is an exact
# URL, or a prefix ending in "*". Any scheme is accepted.
ALLOWED_REDIRECT_URIS_ENV = "MCP_OAUTH_ALLOWED_REDIRECT_URIS"

# The consent page, on the web interface's origin. Outside the endpoint's mount.
CONSENT_PATH = "/mcp-oauth/consent"

CODE_LIFETIME_SECONDS = 10 * 60
# How long a user has to sign in and decide after the client starts the authorization request.
PENDING_LIFETIME_SECONDS = 10 * 60
ACCESS_LIFETIME_SECONDS = 60 * 60
REFRESH_LIFETIME_SECONDS = 30 * 24 * 60 * 60

# Bytes of randomness in each code, token and request id. The SDK asks for at least 160 bits.
RANDOM_BYTES = 32

LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

# Percent-decoding rounds before a redirect path that still decodes is refused.
MAX_DECODE_ROUNDS = 5

# Client authentication at the token and revocation endpoints. "none" is for public clients,
# which use PKCE. "private_key_jwt" is for metadata-document clients whose document carries its
# keys inline.
TOKEN_ENDPOINT_AUTH_METHODS = ["none", "private_key_jwt"]
# The only method a client can register with through Dynamic Client Registration.
REGISTRATION_AUTH_METHOD = "none"

AUTHORIZATION_SERVER_METADATA_PATH = "/.well-known/oauth-authorization-server"
AUTHORIZE_PATH = "/authorize"
TOKEN_PATH = "/token"
REVOKE_PATH = "/revoke"

DISALLOWED_REDIRECT_MESSAGE = (
    "Redirect URI {uri!r} is not allowed. Use a loopback http address (localhost, 127.0.0.1 or "
    "::1), or ask an administrator to add it to " + ALLOWED_REDIRECT_URIS_ENV + "."
)

CLIENT_EXISTS_MESSAGE = "A client with this client_id is already registered."

UNSUPPORTED_REGISTRATION_METHOD_MESSAGE = (
    "token_endpoint_auth_method {method!r} is not supported for registration. Register a public "
    "client with 'none' and use PKCE, or publish a Client ID Metadata Document."
)

WRONG_RESOURCE_MESSAGE = (
    "Tokens from this server are only for {expected}. The request named {requested!r}."
)

UNLISTED_REDIRECT_MESSAGE = "Redirect URI {uri!r} is not registered for this client."

CODE_UNUSABLE_MESSAGE = "The authorization code was already used or has expired."
REFRESH_UNUSABLE_MESSAGE = "The refresh token was already used, revoked or has expired."
INACTIVE_ACCOUNT_MESSAGE = "The account this grant belongs to is not active."


def _body_limited(app):
    """The SDK's request body limit around an ASGI app, as mcp.server.auth.routes applies it."""
    return RequestBodyLimitMiddleware(app, DEFAULT_MAX_REQUEST_BODY_SIZE)


def _cors(app, allow_methods: list[str]):
    """CORS around an ASGI app, with the settings of mcp.server.auth.routes.cors_middleware."""
    return CORSMiddleware(
        app=app,
        allow_origins="*",
        allow_methods=allow_methods,
        allow_headers=[MCP_PROTOCOL_VERSION_HEADER],
    )


def new_value() -> str:
    """A random code, token or request id."""
    return secrets.token_urlsafe(RANDOM_BYTES)


def parse_allowed_redirect_uris(raw: str) -> list[str]:
    return [entry.strip() for entry in (raw or "").split(",") if entry.strip()]


def allowed_redirect_uris_from_env() -> list[str]:
    return parse_allowed_redirect_uris(os.environ.get(ALLOWED_REDIRECT_URIS_ENV, ""))


def _normalized(uri: str) -> str:
    """The URL as pydantic serializes it, which is how registered redirect URIs are compared."""
    try:
        return str(AnyUrl(uri))
    except ValueError:
        return uri


def _has_dot_segments(path: str) -> bool:
    """Whether the path has a "." or ".." segment, also when percent-encoded.

    The path is decoded until it stops changing, so "%2e%2e" and "%252e%252e" are caught. A path
    that still changes after MAX_DECODE_ROUNDS decodings is treated as having dot segments.
    """
    decoded = path
    for _ in range(MAX_DECODE_ROUNDS):
        once = unquote(decoded)
        if once == decoded:
            break
        decoded = once
    else:
        if unquote(decoded) != decoded:
            return True
    return any(segment in (".", "..") for segment in decoded.replace("\\", "/").split("/"))


def _origin(parts: SplitResult) -> Optional[tuple[str, str, Optional[int]]]:
    """Scheme, host and port of a parsed URL, lowercased, or None when the port is invalid."""
    try:
        port = parts.port
    except ValueError:
        return None
    return parts.scheme.lower(), (parts.hostname or "").lower(), port


def _path_and_query(parts: SplitResult) -> str:
    return parts.path + (f"?{parts.query}" if parts.query else "")


def _prefix_entry_matches(parts: SplitResult, entry: str) -> bool:
    """An entry ending in "*": same scheme, host and port, and a path that starts with its path."""
    try:
        prefix = urlsplit(entry[:-1])
    except ValueError:
        return False
    origin = _origin(parts)
    if origin is None or origin != _origin(prefix):
        return False
    return _path_and_query(parts).startswith(_path_and_query(prefix))


def redirect_uri_allowed(uri: str, allowed: Iterable[str]) -> bool:
    """Loopback http on any port, or a match for an allowlist entry.

    An entry ending in "*" matches a URI with exactly the entry's scheme, host and port whose path
    starts with the entry's path. Any other entry must equal the URI. URIs with user info, a
    fragment or dot segments (also percent-encoded) are refused first.
    """
    try:
        parts = urlsplit(uri)
    except ValueError:
        return False
    if parts.username is not None or parts.password is not None:
        return False
    if parts.fragment or _has_dot_segments(parts.path):
        return False
    if _origin(parts) is None:
        return False
    if parts.scheme == "http" and parts.hostname in LOOPBACK_HOSTS:
        return True
    for entry in allowed:
        if entry.endswith("*"):
            if _prefix_entry_matches(parts, entry):
                return True
        elif _normalized(entry) == _normalized(uri):
            return True
    return False


def _same_loopback_redirect(requested: str, registered: str) -> bool:
    """RFC 8252 §7.3: a loopback redirect matches a registered one on any port.

    Host, path and query must be equal. A path with dot segments never matches.
    """
    a, b = urlsplit(requested), urlsplit(registered)
    return (
        a.scheme == b.scheme == "http"
        and a.hostname in LOOPBACK_HOSTS
        and a.hostname == b.hostname
        and not _has_dot_segments(a.path)
        and (a.path or "/") == (b.path or "/")
        and a.query == b.query
        and a.username is None
        and a.password is None
    )


def resource_matches(requested: str, resource_identifier: str) -> bool:
    """Whether a resource indicator names this endpoint. A trailing slash is ignored."""
    return requested.rstrip("/") == resource_identifier.rstrip("/")


class RegisteredClient(OAuthClientInformationFull):
    """A client stored by Dynamic Client Registration.

    Every use re-applies the current redirect-URI policy, so narrowing the allowlist also refuses
    clients registered before the change.
    """

    allowed_redirect_uris: list[str] = Field(default_factory=list, exclude=True)

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is None:
            resolved = super().validate_redirect_uri(None)
        else:
            resolved = None
            for registered in self.redirect_uris or []:
                if redirect_uri == registered or _same_loopback_redirect(
                    str(redirect_uri), str(registered)
                ):
                    resolved = redirect_uri
                    break
            if resolved is None:
                raise InvalidRedirectUriError(
                    UNLISTED_REDIRECT_MESSAGE.format(uri=str(redirect_uri))
                )
        if not redirect_uri_allowed(str(resolved), self.allowed_redirect_uris):
            raise InvalidRedirectUriError(DISALLOWED_REDIRECT_MESSAGE.format(uri=str(resolved)))
        return resolved


class MetadataDocumentClient(OAuthClientInformationFull):
    """A client described by its Client ID Metadata Document.

    Redirect URIs must be listed in the document and must also pass the redirect-URI policy.
    fastmcp's private_key_jwt authenticator reads `cimd_document`.
    """

    cimd_document: CIMDDocument | None = Field(default=None, exclude=True)
    allowed_redirect_uris: list[str] = Field(default_factory=list, exclude=True)

    def _check(self, uri: str) -> None:
        listed = self.cimd_document.redirect_uris if self.cimd_document else []
        if not any(matches_allowed_pattern(uri.rstrip("/"), p.rstrip("/")) for p in listed):
            raise InvalidRedirectUriError(UNLISTED_REDIRECT_MESSAGE.format(uri=uri))
        if not redirect_uri_allowed(uri, self.allowed_redirect_uris):
            raise InvalidRedirectUriError(DISALLOWED_REDIRECT_MESSAGE.format(uri=uri))

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is None:
            listed = self.cimd_document.redirect_uris if self.cimd_document else []
            if len(listed) != 1 or "*" in listed[0]:
                raise InvalidRedirectUriError(
                    "redirect_uri must be specified unless the client's document lists exactly "
                    "one redirect URI without wildcards"
                )
            redirect_uri = AnyUrl(listed[0])
        self._check(str(redirect_uri))
        return redirect_uri


class EndpointOAuthProvider(OAuthProvider):
    """Authorization server for the MCP endpoint. Tokens resolve to Open WebUI user ids.

    `service_url` is WEBUI_URL: the issuer, and the origin of the authorize, token, register,
    revoke and consent routes. `resource_identifier` is the endpoint's URL, which every access
    token carries and which verification requires.
    """

    def __init__(
        self,
        *,
        service_url: str,
        resource_identifier: str,
        allowed_redirect_uris: Iterable[str] = (),
        store: McpOAuthTable = McpOAuth,
        document_fetcher: Optional[CIMDFetcher] = None,
    ):
        super().__init__(
            base_url=service_url,
            resource_base_url=resource_identifier,
            client_registration_options=ClientRegistrationOptions(enabled=True),
            revocation_options=RevocationOptions(enabled=True),
        )
        self.service_url = service_url.rstrip("/")
        self.resource_identifier = resource_identifier
        self.allowed_redirect_uris = tuple(allowed_redirect_uris)
        self.store = store
        # Documents are cached in this process according to their HTTP cache headers.
        self.document_fetcher = document_fetcher or CIMDFetcher()
        # Used only to verify private_key_jwt assertions of metadata-document clients.
        self._assertion_manager = CIMDClientManager()

    @property
    def issuer(self) -> str:
        """The advertised issuer, exactly as the metadata serializes it. Sent as `iss`."""
        return str(self.issuer_url)

    @property
    def consent_url(self) -> str:
        return f"{self.service_url}{CONSENT_PATH}"

    @property
    def token_endpoint_url(self) -> str:
        return f"{self.service_url}{TOKEN_PATH}"

    # Metadata and routes

    @property
    def scopes_supported(self) -> list[str] | None:
        """None, so the protected resource metadata has no scopes_supported field.

        A client that copies the advertised scopes into its registration is limited to them. No
        scope is required here.
        """
        return None

    def _authorization_server_metadata(self):
        metadata = build_metadata(
            self.base_url,
            self.service_documentation_url,
            self.client_registration_options,
            self.revocation_options,
        )
        metadata.issuer = self.issuer_url
        metadata.token_endpoint_auth_methods_supported = list(TOKEN_ENDPOINT_AUTH_METHODS)
        metadata.revocation_endpoint_auth_methods_supported = list(TOKEN_ENDPOINT_AUTH_METHODS)
        metadata.authorization_response_iss_parameter_supported = True
        metadata.client_id_metadata_document_supported = True
        return metadata

    def _client_authenticator(self) -> PrivateKeyJWTClientAuthenticator:
        """The SDK's authenticator, extended by fastmcp to verify private_key_jwt assertions."""
        return PrivateKeyJWTClientAuthenticator(
            provider=self,
            cimd_manager=self._assertion_manager,
            token_endpoint_url=self.token_endpoint_url,
        )

    def _authorize_endpoint(self):
        """The SDK's authorize handler, with `iss` added to every redirect back to the client.

        Its error redirects are built inside the SDK. The redirect to the consent page is left
        unchanged; the consent page adds `iss` to its own redirects.
        """
        handler = AuthorizationHandler(self)

        async def authorize(request: Request):
            response = await handler.handle(request)
            location = response.headers.get("location")
            if location and not location.startswith(self.consent_url):
                response.headers["location"] = construct_redirect_uri(location, iss=self.issuer)
            return response

        return authorize

    def _revoke_endpoint(self):
        """RFC 7009 revocation for public and private_key_jwt clients.

        The SDK's revocation handler requires a client_secret form field, which public clients do
        not send, so it answers them with 400. This handler authenticates the client with the same
        authenticator as the token endpoint, then revokes a token that belongs to that client.
        Unknown tokens get 200, as RFC 7009 §2.2 requires.
        """
        authenticator = self._client_authenticator()
        no_store = {"Cache-Control": "no-store", "Pragma": "no-cache"}

        async def revoke(request: Request):
            try:
                client = await authenticator.authenticate_request(request)
            except AuthenticationError as error:
                return JSONResponse(
                    {"error": "invalid_client", "error_description": error.message},
                    status_code=401,
                    headers=no_store,
                )
            form = await request.form()
            value = form.get("token")
            if not isinstance(value, str) or not value:
                return JSONResponse(
                    {"error": "invalid_request", "error_description": "Missing token"},
                    status_code=400,
                    headers=no_store,
                )
            loaded = await self.load_access_token(value) or await self.load_refresh_token(
                client, value
            )
            if loaded is not None and loaded.client_id == client.client_id:
                await self.revoke_token(loaded)
            return Response(status_code=200, headers=no_store)

        return revoke

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        """The library's routes, with four replaced.

        - Metadata: advertises the supported client authentication methods, `iss` and metadata
          documents.
        - Authorize: adds `iss` to redirects back to the client.
        - Token: accepts private_key_jwt from metadata-document clients.
        - Revoke: accepts public clients without a client_secret field, and private_key_jwt.

        Authorize, token and revoke are rebuilt with the SDK's request body limit
        (RequestBodyLimitMiddleware with DEFAULT_MAX_REQUEST_BODY_SIZE) in the SDK's order: CORS
        outside, then the body limit, then the handler. Register keeps the SDK's endpoint, which
        already has the limit.
        """
        routes = []
        for route in super().get_routes(mcp_path):
            if not isinstance(route, Route):
                routes.append(route)
                continue
            if route.path == AUTHORIZATION_SERVER_METADATA_PATH:
                handler = MetadataHandler(self._authorization_server_metadata())
                route = Route(
                    route.path,
                    endpoint=cors_middleware(handler.handle, ["GET", "OPTIONS"]),
                    methods=["GET", "OPTIONS"],
                    name=route.name,
                    include_in_schema=route.include_in_schema,
                )
            elif route.path == AUTHORIZE_PATH:
                route = Route(
                    AUTHORIZE_PATH,
                    endpoint=_body_limited(request_response(self._authorize_endpoint())),
                    methods=["GET", "POST"],
                )
            elif route.path == TOKEN_PATH:
                token_handler = TokenHandler(
                    provider=self, client_authenticator=self._client_authenticator()
                )
                route = Route(
                    TOKEN_PATH,
                    endpoint=_cors(
                        _body_limited(request_response(token_handler.handle)), ["POST", "OPTIONS"]
                    ),
                    methods=["POST", "OPTIONS"],
                )
            elif route.path == REVOKE_PATH:
                route = Route(
                    REVOKE_PATH,
                    endpoint=_cors(
                        _body_limited(request_response(self._revoke_endpoint())),
                        ["POST", "OPTIONS"],
                    ),
                    methods=["POST", "OPTIONS"],
                )
            routes.append(route)
        return routes

    # Clients

    def is_metadata_document_client_id(self, client_id: str) -> bool:
        return self.document_fetcher.is_cimd_client_id(client_id)

    async def _metadata_document_client(self, client_id: str) -> MetadataDocumentClient | None:
        """The client described by the document at `client_id`, or None when it is refused.

        The document must be valid JSON whose `client_id` equals the URL exactly, with a
        `client_name` and `redirect_uris`. A private_key_jwt document must carry its keys inline:
        fetching a `jwks_uri` would be an outbound call other than the document fetch.
        """
        try:
            document = await self.document_fetcher.fetch(client_id)
        except (CIMDFetchError, CIMDValidationError) as error:
            log.warning("Refused client metadata document %s: %s", client_id, error)
            return None
        if str(document.client_id) != client_id:
            log.warning(
                "Refused client metadata document %s: its client_id is %s",
                client_id,
                document.client_id,
            )
            return None
        if not document.client_name:
            log.warning("Refused client metadata document %s: no client_name", client_id)
            return None
        if not document.redirect_uris:
            log.warning("Refused client metadata document %s: no redirect_uris", client_id)
            return None
        if document.token_endpoint_auth_method == "private_key_jwt" and (
            not document.jwks or document.jwks_uri
        ):
            # fastmcp's assertion validator fetches jwks_uri when it is present, even alongside
            # inline keys.
            log.warning(
                "Refused client metadata document %s: private_key_jwt needs inline jwks and no "
                "jwks_uri",
                client_id,
            )
            return None
        return MetadataDocumentClient(
            client_id=client_id,
            client_name=document.client_name,
            grant_types=document.grant_types,
            response_types=document.response_types,
            scope=document.scope,
            token_endpoint_auth_method=document.token_endpoint_auth_method,
            cimd_document=document,
            allowed_redirect_uris=list(self.allowed_redirect_uris),
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if self.is_metadata_document_client_id(client_id):
            return await self._metadata_document_client(client_id)
        info = await asyncio.to_thread(self.store.get_client, client_id)
        if info is None:
            return None
        return RegisteredClient.model_validate(
            {
                **info,
                "client_id": client_id,
                "allowed_redirect_uris": list(self.allowed_redirect_uris),
            }
        )

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        method = client_info.token_endpoint_auth_method
        if method != REGISTRATION_AUTH_METHOD:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description=UNSUPPORTED_REGISTRATION_METHOD_MESSAGE.format(method=method),
            )
        for uri in client_info.redirect_uris or []:
            if not redirect_uri_allowed(str(uri), self.allowed_redirect_uris):
                raise RegistrationError(
                    error="invalid_redirect_uri",
                    error_description=DISALLOWED_REDIRECT_MESSAGE.format(uri=str(uri)),
                )
        info = client_info.model_dump(mode="json", exclude={"client_secret"}, exclude_none=True)
        try:
            await asyncio.to_thread(self.store.insert_client, client_info.client_id, info)
        except ClientExistsError:
            raise RegistrationError(
                error="invalid_client_metadata", error_description=CLIENT_EXISTS_MESSAGE
            )

    # Authorization

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        """Store the request and send the browser to the consent page.

        The consent page signs the user in through the web interface when needed, and issues the
        code only after the user approves.
        """
        if params.resource is not None and not resource_matches(
            params.resource, self.resource_identifier
        ):
            raise AuthorizeError(
                error="invalid_target",
                error_description=WRONG_RESOURCE_MESSAGE.format(
                    expected=self.resource_identifier, requested=params.resource
                ),
            )
        request_id = new_value()
        await asyncio.to_thread(
            self.store.insert_authorization,
            request_id,
            client_id=client.client_id,
            redirect_uri=str(params.redirect_uri),
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            state=params.state,
            code_challenge=params.code_challenge,
            scopes=list(params.scopes or []),
            resource=self.resource_identifier,
            expires_at=int(time.time()) + PENDING_LIFETIME_SECONDS,
        )
        return f"{self.consent_url}?{urlencode({'request': request_id})}"

    def issue_code(self, authorization: AuthorizationRecord, user_id: str) -> str:
        """Store a code for an approved request and return it. Called by the consent page."""
        code = new_value()
        self.store.insert_code(
            code,
            client_id=authorization.client_id,
            user_id=user_id,
            redirect_uri=authorization.redirect_uri,
            redirect_uri_provided_explicitly=authorization.redirect_uri_provided_explicitly,
            code_challenge=authorization.code_challenge,
            scopes=authorization.scopes,
            resource=authorization.resource,
            expires_at=int(time.time()) + CODE_LIFETIME_SECONDS,
        )
        return code

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        record = await asyncio.to_thread(self.store.get_code, authorization_code)
        if record is None:
            # A code presented again after its exchange revokes the tokens issued for it.
            await asyncio.to_thread(self.store.revoke_reused_code, authorization_code)
            return None
        if record.client_id != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=record.scopes,
            expires_at=record.expires_at,
            client_id=record.client_id,
            code_challenge=record.code_challenge,
            redirect_uri=AnyUrl(record.redirect_uri),
            redirect_uri_provided_explicitly=record.redirect_uri_provided_explicitly,
            resource=record.resource,
            subject=record.user_id,
        )

    def _token_response(self, issued) -> OAuthToken:
        return OAuthToken(
            access_token=issued.access_token,
            token_type="Bearer",
            expires_in=ACCESS_LIFETIME_SECONDS,
            scope=" ".join(issued.scopes) or None,
            refresh_token=issued.refresh_token,
        )

    def _lifetimes(self) -> dict:
        now = int(time.time())
        return {
            "access_expires_at": now + ACCESS_LIFETIME_SECONDS,
            "refresh_expires_at": now + REFRESH_LIFETIME_SECONDS,
        }

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        """Consume the code with one conditional UPDATE and issue tokens for its user."""
        if await asyncio.to_thread(active_account, authorization_code.subject) is None:
            raise TokenError(error="invalid_grant", error_description=INACTIVE_ACCOUNT_MESSAGE)
        issued = await asyncio.to_thread(
            lambda: self.store.exchange_code(
                authorization_code.code,
                client_id=client.client_id,
                new_access=new_value(),
                new_refresh=new_value(),
                **self._lifetimes(),
            )
        )
        if issued is None:
            raise TokenError(error="invalid_grant", error_description=CODE_UNUSABLE_MESSAGE)
        return self._token_response(issued)

    # Refresh

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        record = await asyncio.to_thread(self.store.get_token, refresh_token, REFRESH)
        if record is None:
            # A rotated refresh token presented again revokes its whole grant.
            await asyncio.to_thread(self.store.revoke_reused_refresh, refresh_token)
            return None
        if record.client_id != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=record.client_id,
            scopes=record.scopes,
            expires_at=record.expires_at,
            subject=record.user_id,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        """Revoke the presented refresh token and issue a new pair, in one transaction."""
        if await asyncio.to_thread(active_account, refresh_token.subject) is None:
            raise TokenError(error="invalid_grant", error_description=INACTIVE_ACCOUNT_MESSAGE)
        issued = await asyncio.to_thread(
            lambda: self.store.rotate_refresh(
                refresh_token.token,
                client_id=client.client_id,
                scopes=list(scopes),
                new_access=new_value(),
                new_refresh=new_value(),
                **self._lifetimes(),
            )
        )
        if issued is None:
            raise TokenError(error="invalid_grant", error_description=REFRESH_UNUSABLE_MESSAGE)
        return self._token_response(issued)

    # Access

    async def load_access_token(self, token: str) -> AccessToken | None:
        """The access token when it is known, unexpired, unrevoked and for this endpoint."""
        record = await asyncio.to_thread(self.store.get_token, token, ACCESS)
        if record is None:
            return None
        if not resource_matches(record.resource, self.resource_identifier):
            return None
        return AccessToken(
            token=token,
            client_id=record.client_id,
            scopes=record.scopes,
            expires_at=record.expires_at,
            resource=record.resource,
            subject=record.user_id,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """load_access_token, then the account's current role. Runs on every request."""
        access = await self.load_access_token(token)
        if access is None:
            return None
        if await asyncio.to_thread(active_account, access.subject) is None:
            return None
        return access

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revoke the token and every other token issued from the same code."""
        await asyncio.to_thread(self.store.revoke_grant, token.token)


def build_provider(service_url: str, resource_identifier: str) -> EndpointOAuthProvider:
    return EndpointOAuthProvider(
        service_url=service_url,
        resource_identifier=resource_identifier,
        allowed_redirect_uris=allowed_redirect_uris_from_env(),
    )


def consent_request_path(request_id: Optional[str]) -> str:
    """The consent page's path for a request id. Path only, as the sign-in page requires."""
    return f"{CONSENT_PATH}?{urlencode({'request': request_id or ''})}"
