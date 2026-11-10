"""Artifact listing (#58): the burst that restarted prod at 07:26 UTC on 2026-10-21.

On page load the browser asks for the artifact list of every recent chat.
Each listing walks the chat's sandbox on JuiceFS and reads provenance from
its images, HTML pages and Zarr stores; the route also checked access by
loading the whole chat. All of it ran on the event loop.
"""

import asyncio
from unittest.mock import patch

import httpx

from perf_harness import LoopProbe, check_budget, db_delay, fs_delay, record
from perf_harness.app_data import app_with, call_tool, ensure_user, insert_chat
from perf_harness.data import big_chat, build_sandbox

# Entries per chat in the 07:26 UTC burst, largest first (from prod logs).
SANDBOX_SIZES = [753, 314, 267, 204, 105, 83, 54, 22, 21, 14, 14, 11, 10, 8, 7, 6, 5, 3, 3, 2]


def _chats_with_sandboxes(artifacts_dir):
    user = ensure_user()
    chat_ids = []
    for i, entries in enumerate(SANDBOX_SIZES):
        size = 1_500_000 if entries > 100 else 150_000
        chat_id = insert_chat(user.id, big_chat(size))
        build_sandbox(artifacts_dir / chat_id, entries, seed=i)
        chat_ids.append(chat_id)
    return user, chat_ids


def test_recent_chats_artifact_burst(tmp_path):
    from open_webui.routers import artifacts as artifacts_router

    juicefs = tmp_path / "juicefs"
    artifacts = juicefs / "artifacts"
    user, chat_ids = _chats_with_sandboxes(artifacts)
    app = app_with(artifacts_router.router, "/api/v1/chats", user)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://perf") as client:
            async with LoopProbe() as probe:
                responses = await asyncio.gather(
                    *(client.get(f"/api/v1/chats/{chat_id}/artifacts") for chat_id in chat_ids)
                )
        assert all(r.status_code == 200 for r in responses)
        return probe.stats

    with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts), db_delay(), fs_delay([juicefs]):
        stats = asyncio.run(run())

    record("artifacts: 20 recent chats listed at once", stats, entries=sum(SANDBOX_SIZES))
    check_budget(stats, max_lag_ms=250, blocked_pct=20)


def test_list_artifacts_tool_on_a_large_sandbox(tmp_path):
    from open_webui.utils import builtin_tools

    juicefs = tmp_path / "juicefs"
    artifacts = juicefs / "artifacts"
    user = ensure_user()
    chat_id = insert_chat(user.id, big_chat(1_500_000))
    build_sandbox(artifacts / chat_id, 753)

    async def run():
        async with LoopProbe() as probe:
            out = await call_tool(
                builtin_tools.list_artifacts,
                __user__={"id": user.id}, __metadata__={"chat_id": chat_id}
            )
        assert "plots/" in out
        return probe.stats

    with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts), db_delay(), fs_delay([juicefs]):
        stats = asyncio.run(run())

    record("artifacts: list_artifacts tool, 753 entries", stats)
    check_budget(stats, max_lag_ms=100)
