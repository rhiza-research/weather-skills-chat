"""Live updates (#7): socket connects and chat-changed broadcasts.

Each socket connect looks the user up in the database on the event loop, then
broadcasts the user list and model usage to every client. After every saved
turn, edit, pin or archive, publish_chat_committed loads the whole chat to
build its sidebar row and tell the chat's watchers, also on the loop.

Not modelled: sending each broadcast to N real websocket clients. That cost
grows with the number of connected tabs and is not calibrated here.
"""

import asyncio
from unittest.mock import AsyncMock, patch

from perf_harness import LoopProbe, check_budget, db_delay, record
from perf_harness.app_data import ensure_user, insert_chat
from perf_harness.data import big_chat

CONNECTS = 50  # a reconnect burst after a restart or a network blip
COMMITS = 20


def test_socket_reconnect_burst(tmp_path):
    from open_webui.socket import main as socket_main
    from open_webui.utils.auth import create_token

    user = ensure_user()
    token = create_token({"id": user.id})

    async def run():
        async with LoopProbe() as probe:
            for i in range(CONNECTS):
                await socket_main.connect(f"sid-{i}", {}, {"token": token})
                await asyncio.sleep(0.005)  # connects arrive a few ms apart
        return probe.stats

    with patch.object(socket_main.sio, "emit", AsyncMock()), db_delay():
        stats = asyncio.run(run())
    for i in range(CONNECTS):
        socket_main.SESSION_POOL.pop(f"sid-{i}", None)
    socket_main.USER_POOL.pop(user.id, None)
    record(f"realtime: {CONNECTS} socket connects", stats)
    check_budget(stats, max_lag_ms=3, blocked_pct=5, pending="#7 socket connect lookups")


def test_chat_committed_broadcasts_on_a_large_chat(tmp_path):
    from open_webui.utils import chat_realtime

    user = ensure_user()
    chat_id = insert_chat(user.id, big_chat(1_500_000))

    async def run():
        async with LoopProbe() as probe:
            for _ in range(COMMITS):
                await chat_realtime.publish_chat_committed(chat_id)
                await asyncio.sleep(0.02)
        return probe.stats

    with patch.object(chat_realtime.sio, "emit", AsyncMock()), db_delay():
        stats = asyncio.run(run())
    record(f"realtime: {COMMITS} chat-committed broadcasts for a 1.5 MB chat", stats)
    check_budget(stats, max_lag_ms=10, blocked_pct=10, pending="#7 publish_chat_committed, #6 chat load logging")
