"""Identifies the chat rows that hold MCP endpoint sessions.

The endpoint writes each call into its session. The interface can view the session but cannot
replace or edit its messages, because a tab's full-chat save would drop calls made after the tab
loaded.

No dependencies beyond the standard library, so the chat router can import it without importing
the MCP package.
"""

# Chat blob key that marks an endpoint session. Written when the endpoint inserts the row.
SESSION_MARKER_KEY = "mcp_endpoint_session"

# Chat blob keys holding the session's messages.
TRANSCRIPT_KEYS = frozenset({"history", "messages"})

READ_ONLY_MESSAGE = (
    "This chat is an MCP endpoint session. Its messages are written by the endpoint and cannot be "
    "changed from the interface."
)


def is_endpoint_session(chat_blob) -> bool:
    """Whether a chat blob carries the endpoint session marker."""
    return bool((chat_blob or {}).get(SESSION_MARKER_KEY))
