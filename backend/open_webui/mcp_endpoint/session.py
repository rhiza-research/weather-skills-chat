"""The chat row that holds an account's endpoint runs.

Each account has one endpoint session per organization, stored as a private chat row with that
organization_id. The artifact store authorizes by chat id, and the interface displays the row's
tool calls.

The row is found by a marker key written into the chat blob at insert. No pointer to it is stored
in user-editable settings, because those accept arbitrary values from the account and could name
another account's row.
"""

import logging

from fastmcp.exceptions import ToolError

from open_webui.models.chats import ChatForm, Chats
from open_webui.models.users import UserModel

log = logging.getLogger(__name__)

# Chat blob key that marks an endpoint session. Written in the insert and found by scanning the
# account's own chats.
SESSION_MARKER_KEY = "mcp_endpoint_session"

SESSION_TITLE = "MCP session"

NO_SESSION_MESSAGE = (
    "Could not create a session for this account. Nothing was run."
)


def _blob() -> dict:
    """The chat blob for a new endpoint session: the interface's chat shape plus the marker."""
    return {
        SESSION_MARKER_KEY: True,
        "title": SESSION_TITLE,
        "models": [],
        "history": {"messages": {}, "currentId": None},
        "messages": [],
    }


def _is_endpoint_session(chat) -> bool:
    return bool((chat.chat or {}).get(SESSION_MARKER_KEY))


def _owns(chat, account: UserModel) -> bool:
    """Whether the chat's user_id is the account's id. Organization and admin access are not
    counted."""
    return chat is not None and chat.user_id == account.id


def _existing(account: UserModel, organization_id: str):
    """The account's oldest endpoint session in the organization, or None.

    Choosing the oldest makes concurrent first calls agree on one row: both insert, both scan, both
    pick the same one.
    """
    owned = [
        chat
        for chat in Chats.get_chats_by_user_id(account.id)
        if _is_endpoint_session(chat)
        and _owns(chat, account)
        and chat.organization_id == organization_id
    ]
    owned.sort(key=lambda chat: (chat.created_at or 0, chat.id))
    return owned[0] if owned else None


def owned_session(account: UserModel, organization_id: str):
    """The account's endpoint session in the organization, created if none exists. Looked up on
    every call."""
    existing = _existing(account, organization_id)
    if existing is not None:
        return existing

    # Private, so other members of the organization cannot read the row.
    created = Chats.insert_new_chat(
        account.id,
        ChatForm(chat=_blob(), organization_id=organization_id, visibility="private"),
    )
    if created is None:
        raise ToolError(NO_SESSION_MESSAGE)

    winner = _existing(account, organization_id)
    if winner is None:
        raise ToolError(NO_SESSION_MESSAGE)
    if winner.id != created.id:
        # A concurrent call created an older session. Use it and delete this one, scoped to this
        # account.
        log.info(
            "Endpoint session %s already existed for this account; discarding %s",
            winner.id,
            created.id,
        )
        Chats.delete_chat_by_id_and_user_id(created.id, account.id)
    return winner


def session_id(account: UserModel, organization_id: str) -> str:
    """The session's id. Runs write to the artifact directory with this name."""
    return owned_session(account, organization_id).id
