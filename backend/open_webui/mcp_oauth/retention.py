"""Deletes the authorization server's rows that can no longer be used.

Every process runs the loop. The deletes are conditional on expiry and state, so several replicas
running them at once delete each row once and leave live rows alone.
"""

import asyncio
import logging
import time

from open_webui.models.mcp_oauth import McpOAuth, McpOAuthTable

log = logging.getLogger(__name__)

# How often each process deletes unusable rows.
PURGE_INTERVAL_SECONDS = 60 * 60

# A registered client with no live token, code or pending request is deleted this long after it
# registered.
IDLE_CLIENT_SECONDS = 30 * 24 * 60 * 60


def purge_once(store: McpOAuthTable = McpOAuth) -> dict[str, int]:
    deleted = store.purge(now=int(time.time()), idle_client_seconds=IDLE_CLIENT_SECONDS)
    if any(deleted.values()):
        log.info("MCP OAuth retention deleted %s", deleted)
    return deleted


async def purge_forever(interval: float = PURGE_INTERVAL_SECONDS) -> None:
    """Run purge_once now and then every `interval` seconds. A failed run is logged and retried."""
    while True:
        try:
            await asyncio.to_thread(purge_once)
        except Exception:
            log.exception("MCP OAuth retention run failed")
        await asyncio.sleep(interval)
