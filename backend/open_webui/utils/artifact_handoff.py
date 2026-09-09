"""One-time URLs that serve an artifact without authentication.

For clients such as a shell command that have no bearer token. The URL serves the artifact to the
first request and to no later request.

Claiming a nonce uses Redis GETDEL. Without REDIS_URL, minting is refused, because an in-process
store would not be single use across workers.
"""

import logging
import secrets

from open_webui.env import REDIS_URL

log = logging.getLogger(__name__)

# The nonce is the only credential in the URL.
NONCE_BYTES = 32

# Unredeemed handoffs expire after this many seconds.
HANDOFF_TTL_SECONDS = 300

# Prefix for handoff keys in Redis.
KEY_PREFIX = "mcp:artifact-handoff:"

UNAVAILABLE_MESSAGE = (
    "One-time links need REDIS_URL, which is not set. Request the artifact as content or base64 "
    "to receive it directly, or as a link to open it while signed in."
)


def handoff_available() -> bool:
    """Whether REDIS_URL is set."""
    return bool(str(REDIS_URL or "").strip())


def _client():
    # Imported here so this module imports without the redis package installed.
    import redis

    return redis.Redis.from_url(str(REDIS_URL), decode_responses=True)


def mint(session_id: str, relpath: str) -> str:
    """Store a one-time handoff for one artifact of one session and return its nonce."""
    if not handoff_available():
        raise RuntimeError(UNAVAILABLE_MESSAGE)
    nonce = secrets.token_urlsafe(NONCE_BYTES)
    # The value holds both session and path, so redeeming returns exactly this artifact.
    _client().setex(f"{KEY_PREFIX}{nonce}", HANDOFF_TTL_SECONDS, f"{session_id}\n{relpath}")
    return nonce


def redeem(nonce: str) -> tuple[str, str] | None:
    """Claim a handoff and return (session_id, relpath), or None.

    GETDEL reads and deletes in one command, so only one request gets the value. All failures
    return None.
    """
    if not nonce or not handoff_available():
        return None
    try:
        stored = _client().getdel(f"{KEY_PREFIX}{nonce}")
    except Exception:
        log.exception("Could not redeem an artifact handoff")
        return None
    if not stored or "\n" not in stored:
        return None
    session_id, relpath = stored.split("\n", 1)
    return session_id, relpath
