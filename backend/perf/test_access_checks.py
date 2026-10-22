"""Access checks (#61): routes and tools that check the user may use the chat.

Each check loaded and validated the whole chat (often 1-2 MB) only to read its
owner, organization and visibility, on the event loop.
"""

import asyncio
from unittest.mock import patch

import httpx

from perf_harness import LoopProbe, check_budget, db_delay, fs_delay, record
from perf_harness.app_data import app_with, call_tool, ensure_user, insert_chat
from perf_harness.data import big_chat

CALLS = 30
# Between tool calls the model is generating the next one.
MODEL_GAP_S = 0.01


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


def test_chat_actions_on_a_large_chat(tmp_path):
    from open_webui.routers import chats as chats_router

    user = ensure_user()
    chat_id = insert_chat(user.id, big_chat(1_500_000))
    app = app_with(chats_router.router, "/api/v1/chats", user)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://perf") as client:
            async with LoopProbe() as probe:
                for _ in range(CALLS):
                    response = await client.post(f"/api/v1/chats/{chat_id}/pin")
                    assert response.status_code == 200
        return probe.stats

    with db_delay():
        stats = asyncio.run(run())

    record(f"access checks: {CALLS} pin toggles on a 1.5 MB chat", stats)
    # Still on the loop, so this only guards against getting worse: FastAPI
    # validates and serializes an async route's response there, and this route
    # returns the whole 1.5 MB chat.
    check_budget(stats, max_lag_ms=100, blocked_pct=45)


def test_tool_calls_on_a_large_chat(tmp_path):
    from open_webui.utils import builtin_tools

    juicefs = tmp_path / "juicefs"
    artifacts = juicefs / "artifacts"
    user = ensure_user()
    chat_id = insert_chat(user.id, big_chat(1_500_000))

    async def run():
        async with LoopProbe() as probe:
            for i in range(CALLS):
                out = await call_tool(builtin_tools.create_folder,
                    path=f"plots/week_{i}",
                    __user__={"id": user.id},
                    __metadata__={"chat_id": chat_id},
                )
                assert "week_" in out
                await asyncio.sleep(MODEL_GAP_S)
        return probe.stats

    with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts), db_delay(), fs_delay([juicefs]):
        stats = asyncio.run(run())

    record(f"access checks: {CALLS} create_folder tool calls on a 1.5 MB chat", stats)
    # Only guards against getting worse: the folder is still created on the
    # loop, where chat_sandbox() makes and re-owns the sandbox folders on
    # JuiceFS on every path lookup.
    check_budget(stats, max_lag_ms=200)
