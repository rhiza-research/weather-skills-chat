"""The consent page: signs the user in through the web interface, then asks them to approve.

GET shows the page. Without a valid interface session it redirects to the interface's sign-in page
with a path-only `redirect` back here. An account whose role is not active gets an error page and
is never redirected to the client.

POST records the decision. It must come from the user the page was shown to and carry the form
value issued with that page. Approve stores a code and redirects to the client with it. Deny
redirects to the client with error=access_denied. Both redirects carry `iss` (RFC 9207).
"""

import asyncio
import html
import logging
from typing import Optional
from urllib.parse import quote, urlsplit

from mcp.server.auth.provider import construct_redirect_uri
from mcp.shared.auth import InvalidRedirectUriError
from pydantic import AnyUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from open_webui.mcp_oauth.accounts import ACTIVE_ROLES
from open_webui.mcp_oauth.provider import (
    CONSENT_PATH,
    EndpointOAuthProvider,
    consent_request_path,
    new_value,
)
from open_webui.models.users import UserModel, Users
from open_webui.utils.auth import decode_token

log = logging.getLogger(__name__)

# The interface's sign-in page and the cookie its sign-in sets.
SIGN_IN_PATH = "/auth"
SESSION_COOKIE = "token"

APPROVE = "approve"
DENY = "deny"

# Headers on every page: not cached, not framed, and the request id is not sent as a referrer.
PAGE_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'; default-src 'none'; style-src 'unsafe-inline'",
    "Referrer-Policy": "no-referrer",
}

UNKNOWN_REQUEST_MESSAGE = (
    "This authorization request is unknown, has expired, or was already decided. Start the "
    "connection again from your MCP client."
)
UNKNOWN_CLIENT_MESSAGE = "The client that started this request is not registered."
INACTIVE_ACCOUNT_MESSAGE = (
    "This account is not active. Its role is {role!r}; allowed roles are {active}. An "
    "administrator can activate it in the web interface."
)
SESSION_ENDED_MESSAGE = "Your session ended. Start the connection again from your MCP client."
REFUSED_REDIRECT_MESSAGE = (
    "The client's redirect address is no longer allowed. Start the connection again from your MCP "
    "client."
)
BAD_DECISION_MESSAGE = "The form did not say whether to approve or deny."

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: system-ui, sans-serif; background: #f6f6f6; color: #111; margin: 0; }}
main {{ max-width: 28rem; margin: 10vh auto; padding: 1.5rem; background: #fff;
  border-radius: 0.75rem; box-shadow: 0 1px 3px rgba(0,0,0,0.12); }}
h1 {{ font-size: 1.25rem; margin-top: 0; }}
dt {{ font-weight: 600; margin-top: 0.75rem; }}
dd {{ margin: 0.25rem 0 0; word-break: break-all; }}
.actions {{ display: flex; gap: 0.75rem; margin-top: 1.5rem; }}
button {{ flex: 1; padding: 0.6rem; font-size: 1rem; border-radius: 0.5rem;
  border: 1px solid #999; background: #fff; cursor: pointer; }}
button[value=approve] {{ background: #111; color: #fff; border-color: #111; }}
@media (prefers-color-scheme: dark) {{
  body {{ background: #111; color: #eee; }}
  main {{ background: #1c1c1c; box-shadow: none; }}
  button {{ background: #1c1c1c; color: #eee; border-color: #555; }}
  button[value=approve] {{ background: #eee; color: #111; border-color: #eee; }}
}}
</style>
</head>
<body><main>{body}</main></body>
</html>
"""


def _page(title: str, body: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(
        PAGE.format(title=html.escape(title), body=body),
        status_code=status_code,
        headers=PAGE_HEADERS,
    )


def _error_page(message: str, status_code: int) -> HTMLResponse:
    return _page(
        "Authorization failed",
        f"<h1>Authorization failed</h1><p>{html.escape(message)}</p>",
        status_code,
    )


def signed_in_user(request: Request) -> Optional[UserModel]:
    """The account whose interface session cookie is on the request, whatever its role."""
    session = request.cookies.get(SESSION_COOKIE)
    if not session:
        return None
    data = decode_token(session)
    if not data or "id" not in data:
        return None
    return Users.get_user_by_id(data["id"])


def _inactive_page(account: UserModel) -> HTMLResponse:
    return _error_page(
        INACTIVE_ACCOUNT_MESSAGE.format(
            role=account.role, active=", ".join(sorted(ACTIVE_ROLES))
        ),
        403,
    )


def _sign_in_redirect(provider: EndpointOAuthProvider, request_id: str) -> Response:
    # The sign-in page only follows a path. The value is always this page's own path.
    back = consent_request_path(request_id)
    return RedirectResponse(
        f"{provider.service_url}{SIGN_IN_PATH}?redirect={quote(back, safe='')}",
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )


def _client_rows(client, is_metadata_document: bool) -> str:
    """The client's description rows.

    A metadata-document client's client_id is the https URL its document was fetched from, so it
    is shown. A registered client chose its own name, so the name is labeled as the client's
    claim.
    """
    name = client.client_name or client.client_id
    if is_metadata_document:
        return (
            f"<dt>Client</dt><dd>{html.escape(name)}</dd>"
            f"<dt>Client ID (verified document URL)</dt><dd>{html.escape(client.client_id)}</dd>"
        )
    return (
        "<dt>Client name (provided by the client, not verified)</dt>"
        f"<dd>{html.escape(name)}</dd>"
    )


def _account_row(account: UserModel) -> str:
    return (
        "<dt>Signed in as</dt>"
        f"<dd>{html.escape(account.name)} ({html.escape(account.email)})</dd>"
    )


def _consent_body(
    account_row: str, client_rows: str, redirect_host: str, request_id: str, form_value: str
) -> str:
    return (
        "<h1>Allow access to your account?</h1>"
        "<p>An MCP client wants to run tools on this service as you.</p>"
        "<dl>"
        f"{account_row}"
        f"{client_rows}"
        f"<dt>Returns to</dt><dd>{html.escape(redirect_host)}</dd>"
        "</dl>"
        f'<form method="post" action="{html.escape(CONSENT_PATH)}">'
        f'<input type="hidden" name="request" value="{html.escape(request_id)}">'
        f'<input type="hidden" name="form" value="{html.escape(form_value)}">'
        '<div class="actions">'
        f'<button type="submit" name="decision" value="{DENY}">Deny</button>'
        f'<button type="submit" name="decision" value="{APPROVE}">Approve</button>'
        "</div></form>"
    )


def consent_routes(provider: EndpointOAuthProvider) -> list[Route]:
    store = provider.store

    async def show(request: Request) -> Response:
        request_id = request.query_params.get("request") or ""
        authorization = await asyncio.to_thread(store.get_authorization, request_id)
        if authorization is None:
            return _error_page(UNKNOWN_REQUEST_MESSAGE, 400)

        account = await asyncio.to_thread(signed_in_user, request)
        if account is None:
            return _sign_in_redirect(provider, request_id)
        if account.role not in ACTIVE_ROLES:
            return _inactive_page(account)

        client = await provider.get_client(authorization.client_id)
        if client is None:
            return _error_page(UNKNOWN_CLIENT_MESSAGE, 400)

        form_value = new_value()
        bound = await asyncio.to_thread(
            store.bind_authorization, request_id, account.id, form_value
        )
        if not bound:
            return _error_page(UNKNOWN_REQUEST_MESSAGE, 400)

        redirect = urlsplit(authorization.redirect_uri)
        # A custom-scheme redirect such as com.app:/cb has no authority; show scheme and path.
        redirect_host = redirect.netloc or f"{redirect.scheme}:{redirect.path}"
        return _page(
            "Allow access",
            _consent_body(
                _account_row(account),
                _client_rows(
                    client, provider.is_metadata_document_client_id(client.client_id)
                ),
                redirect_host,
                request_id,
                form_value,
            ),
        )

    async def decide(request: Request) -> Response:
        form = await request.form()
        request_id = str(form.get("request") or "")
        form_value = str(form.get("form") or "")
        decision = form.get("decision")
        if decision not in (APPROVE, DENY):
            return _error_page(BAD_DECISION_MESSAGE, 400)

        account = await asyncio.to_thread(signed_in_user, request)
        if account is None:
            return _error_page(SESSION_ENDED_MESSAGE, 401)
        if account.role not in ACTIVE_ROLES:
            return _inactive_page(account)

        authorization = await asyncio.to_thread(store.get_authorization, request_id)
        if authorization is None:
            return _error_page(UNKNOWN_REQUEST_MESSAGE, 400)

        # The client and the redirect policy may have changed since the request was stored.
        client = await provider.get_client(authorization.client_id)
        if client is None:
            return _error_page(UNKNOWN_CLIENT_MESSAGE, 400)
        try:
            client.validate_redirect_uri(AnyUrl(authorization.redirect_uri))
        except (InvalidRedirectUriError, ValueError):
            return _error_page(REFUSED_REDIRECT_MESSAGE, 400)

        consumed = await asyncio.to_thread(
            store.consume_authorization, request_id, account.id, form_value
        )
        if not consumed:
            return _error_page(UNKNOWN_REQUEST_MESSAGE, 400)

        if decision == APPROVE:
            code = await asyncio.to_thread(provider.issue_code, authorization, account.id)
            location = construct_redirect_uri(
                authorization.redirect_uri,
                code=code,
                state=authorization.state,
                iss=provider.issuer,
            )
        else:
            location = construct_redirect_uri(
                authorization.redirect_uri,
                error="access_denied",
                state=authorization.state,
                iss=provider.issuer,
            )
        return RedirectResponse(location, status_code=303, headers={"Cache-Control": "no-store"})

    return [
        Route(CONSENT_PATH, show, methods=["GET"], name="mcp-oauth-consent"),
        Route(CONSENT_PATH, decide, methods=["POST"], name="mcp-oauth-decision"),
    ]
