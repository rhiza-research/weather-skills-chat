"""Resolves a verified endpoint token to an existing account.

Uses only the verified bearer token. Cookies, interface tokens and API keys are not read.
"""

import logging

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

from open_webui.config import OAUTH_PROVIDERS
from open_webui.models.users import UserModel, Users

log = logging.getLogger(__name__)

# The interface's OpenID client registration name. The interface stores "<name>@<subject>" on the
# account as its OAuth subject.
PROVIDER_REGISTRATION_NAME = "oidc"

# Used when the registration sets no sub_claim, as in the interface.
DEFAULT_SUBJECT_CLAIM = "sub"

NO_TOKEN_MESSAGE = (
    "No verified token on this request."
)

NO_SUBJECT_MESSAGE = (
    "The verified token has no {claim!r} claim."
)

NO_ACCOUNT_MESSAGE = (
    "No account is linked to this identity. Sign in to the web interface once with the same "
    "provider account, then try again."
)

# Roles the interface allows. Not imported, because a test forbids the endpoint from importing the
# interface's auth module.
ACTIVE_ROLES = frozenset({"user", "admin"})

INACTIVE_ACCOUNT_MESSAGE = (
    "This account is not active. Its role is {role!r}; allowed roles are {active}. An "
    "administrator can activate it in the web interface."
)


def subject_claim() -> str:
    """The subject claim name from the oidc registration, as the interface reads it."""
    registration = OAUTH_PROVIDERS.get(PROVIDER_REGISTRATION_NAME) or {}
    return registration.get("sub_claim", DEFAULT_SUBJECT_CLAIM)


def account_key(subject: str) -> str:
    """The account's stored OAuth subject for this identity, in the interface's format."""
    return f"{PROVIDER_REGISTRATION_NAME}@{subject}"


def resolve_caller() -> UserModel:
    """The account whose stored OAuth subject matches the verified token.

    Looks up by subject only, never by email. Does not create or modify accounts. Raises ToolError
    when there is no token, no subject claim, no matching account, or the account's role is not in
    ACTIVE_ROLES.
    """
    token = get_access_token()
    if token is None:
        raise ToolError(NO_TOKEN_MESSAGE)

    claim = subject_claim()
    subject = (token.claims or {}).get(claim)
    if not subject:
        raise ToolError(NO_SUBJECT_MESSAGE.format(claim=claim))

    account = Users.get_user_by_oauth_sub(account_key(str(subject)))
    if account is None:
        raise ToolError(NO_ACCOUNT_MESSAGE)
    if account.role not in ACTIVE_ROLES:
        raise ToolError(
            INACTIVE_ACCOUNT_MESSAGE.format(
                role=account.role, active=", ".join(sorted(ACTIVE_ROLES))
            )
        )
    return account
