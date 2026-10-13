"""Deletes the authorization server's rows that can no longer be used.

Run it from /app/backend with `python -m open_webui.mcp_oauth.retention`. It deletes once, logs the
rows deleted per table and exits 0, or logs the exception and exits 1. Nothing runs it
automatically. The deletes are conditional on expiry and state, so a run that overlaps another
deletes each row once and leaves live rows alone.
"""

import logging
import sys
import time

from open_webui.models.mcp_oauth import McpOAuth, McpOAuthTable

# Named explicitly because under `python -m` this module's __name__ is "__main__".
log = logging.getLogger("open_webui.mcp_oauth.retention")

# A registered client with no live token, code or pending request is deleted this long after it
# registered.
IDLE_CLIENT_SECONDS = 30 * 24 * 60 * 60


def purge_once(store: McpOAuthTable = McpOAuth) -> dict[str, int]:
    return store.purge(now=int(time.time()), idle_client_seconds=IDLE_CLIENT_SECONDS)


def main() -> int:
    """Run purge_once and return the process exit code."""
    try:
        deleted = purge_once()
    except Exception:
        log.exception("MCP OAuth retention run failed")
        return 1
    log.info("MCP OAuth retention deleted %s", deleted)
    return 0


if __name__ == "__main__":
    # The application configures the root logger only when GLOBAL_LOG_LEVEL is set, and then this
    # basicConfig is a no-op. The logger's own level shows the summary when that level is above INFO.
    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    log.setLevel(logging.INFO)
    sys.exit(main())
