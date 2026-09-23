"""Resolves a verified endpoint token to an existing account.

Uses only the verified bearer token. Cookies, interface tokens and API keys are not read. An auth
implementation supplies the body of resolve_caller.
"""

import logging

from open_webui.models.users import UserModel

log = logging.getLogger(__name__)

NO_AUTH_IMPLEMENTATION_MESSAGE = (
    "No auth implementation supplies resolve_caller. The MCP endpoint cannot resolve a caller "
    "without one."
)

# Roles the interface allows. Not imported, because a test forbids the endpoint from importing the
# interface's auth module.
ACTIVE_ROLES = frozenset({"user", "admin"})

INACTIVE_ACCOUNT_MESSAGE = (
    "This account is not active. Its role is {role!r}; allowed roles are {active}. An "
    "administrator can activate it in the web interface."
)


def resolve_caller() -> UserModel:
    """The existing account the current request's verified token was issued to.

    An auth implementation supplies this body. It reads the token from fastmcp's
    get_access_token(), never from cookies, interface tokens or API keys. It does not create or
    modify accounts. It raises ToolError when there is no token, no matching account, or the
    account's role is not in ACTIVE_ROLES, with INACTIVE_ACCOUNT_MESSAGE for the last.
    """
    raise NotImplementedError(NO_AUTH_IMPLEMENTATION_MESSAGE)
