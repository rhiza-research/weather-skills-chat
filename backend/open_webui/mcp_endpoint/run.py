"""Parameters passed to a tool callable when the endpoint runs it.

Contains the caller, the session and the organization. No model and no __event_call__: the MCP
protocol revision this endpoint uses has no server-to-client request channel.
"""

import logging

from fastmcp.exceptions import ToolError

from open_webui.models.users import UserModel

log = logging.getLogger(__name__)

# The skill runner reads the session id from __metadata__ under this key. Without it, the runner
# works in the skill's .work directory, which every account shares, and skips Landlock.
SESSION_METADATA_KEY = "chat_id"

# The skill runner resolves stored secrets in the organization named under this key. Without it, the
# runner uses the caller's personal organization.
ORGANIZATION_METADATA_KEY = "organization_id"

# The runner's "no session" value. It has the same effect as a missing key.
NO_SESSION_SENTINEL = "local"

# Existing flag for runs with no browser attached. Status events are written to the chat row, and
# questions to the user are refused.
HEADLESS_METADATA_KEY = "headless"

REFUSED_WITHOUT_SESSION_MESSAGE = (
    "No session was found for this account. Nothing was run."
)


def _caller(account: UserModel) -> dict:
    """The caller as a __user__ dict: id, email, name and role. No credentials."""
    return {
        "id": account.id,
        "email": account.email,
        "name": account.name,
        "role": account.role,
    }


def caller_only_context(account: UserModel) -> dict:
    """Parameters for building the catalog to list tools.

    Contains only the caller, so listing does not create a session. Callables built with these
    parameters are not invoked.
    """
    return {"__user__": _caller(account)}


def run_context(account: UserModel, session_id: str, organization_id: str) -> dict:
    """Parameters for building the catalog to run a tool.

    Contains the caller and the organization, which the runner uses to resolve the caller's stored
    secrets in that organization, and the session id, which selects the run's directory. Raises
    ToolError for an empty session id or NO_SESSION_SENTINEL.
    """
    if not session_id or session_id == NO_SESSION_SENTINEL:
        raise ToolError(REFUSED_WITHOUT_SESSION_MESSAGE)

    return {
        "__user__": _caller(account),
        "__metadata__": {
            SESSION_METADATA_KEY: session_id,
            ORGANIZATION_METADATA_KEY: organization_id,
            HEADLESS_METADATA_KEY: True,
        },
    }
