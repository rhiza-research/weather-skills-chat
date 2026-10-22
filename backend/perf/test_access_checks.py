"""Access checks (#61): routes and tools that check the user may use the chat.

Each check loaded and validated the whole chat (often 1-2 MB) only to read its
owner, organization and visibility, on the event loop.
"""

import asyncio
from unittest.mock import patch

import httpx

from perf_harness import LoopProbe, check_budget, db_delay, record
from perf_harness.app_data import app_with, ensure_user, insert_chat
from perf_harness.data import big_chat

CALLS = 30


def test_message_events_on_a_large_chat(tmp_path):
    """The access check alone: this route returns a bool, not the chat."""
    from open_webui.routers import chats as chats_router

    user = ensure_user()
    chat_id = insert_chat(user.id, big_chat(1_500_000))
    app = app_with(chats_router.router, "/api/v1/chats", user)

    async def emitter(event):
        return None

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://perf") as client:
            async with LoopProbe() as probe:
                for i in range(CALLS):
                    response = await client.post(
                        f"/api/v1/chats/{chat_id}/messages/m{i}/event",
                        json={"type": "status", "data": {"description": "working"}},
                    )
                    assert response.status_code == 200
        return probe.stats

    with patch.object(chats_router, "get_event_emitter", return_value=emitter), db_delay():
        stats = asyncio.run(run())

    record(f"access checks: {CALLS} message events on a 1.5 MB chat", stats)
    check_budget(stats, max_lag_ms=50, blocked_pct=10)
