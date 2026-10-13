"""Resolves a verified endpoint token to an existing account.

Uses only the verified bearer token. Cookies, interface tokens and API keys are not read.
"""

import logging

from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token

from open_webui.mcp_oauth.accounts import ACTIVE_ROLES
from open_webui.models.users import UserModel, Users

log = logging.getLogger(__name__)

__all__ = ["ACTIVE_ROLES", "resolve_caller"]

NO_TOKEN_MESSAGE = (
    "No verified token on this request."
)

NO_SUBJECT_MESSAGE = (
    "The verified token names no account."
)

NO_ACCOUNT_MESSAGE = (
    "The account this token was issued to no longer exists. Connect the client again."
)

INACTIVE_ACCOUNT_MESSAGE = (
    "This account is not active. Its role is {role!r}; allowed roles are {active}. An "
    "administrator can activate it in the web interface."
)


def resolve_caller() -> UserModel:
    """The account whose id the verified token carries as its subject.

    The authorization server stores the approving user's id on each token. Does not create or
    modify accounts. Raises ToolError when there is no token, no subject, no such account, or the
    account's current role is not in ACTIVE_ROLES.
    """
    token = get_access_token()
    if token is None:
        raise ToolError(NO_TOKEN_MESSAGE)

    subject = token.subject
    if not subject:
        raise ToolError(NO_SUBJECT_MESSAGE)

    account = Users.get_user_by_id(str(subject))
    if account is None:
        raise ToolError(NO_ACCOUNT_MESSAGE)
    if account.role not in ACTIVE_ROLES:
        raise ToolError(
            INACTIVE_ACCOUNT_MESSAGE.format(
                role=account.role, active=", ".join(sorted(ACTIVE_ROLES))
            )
        )
    return account
