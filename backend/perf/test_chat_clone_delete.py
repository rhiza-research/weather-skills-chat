"""Cloning and deleting chats with files (#8).

Cloning a chat copies its whole sandbox into the new chat; deleting a chat
removes its sandbox. Both walk the files on JuiceFS on the event loop.
"""

import asyncio
from unittest.mock import patch

from perf_harness import LoopProbe, check_budget, db_delay, fs_delay, record
from perf_harness.app_data import asgi_client, ensure_user, insert_chat, main_app
from perf_harness.data import big_chat, build_sandbox

ENTRIES = 300


def _chat_with_files(artifacts, seed=0):
    user = ensure_user()
    chat_id = insert_chat(user.id, big_chat(150_000))
    build_sandbox(artifacts / chat_id, ENTRIES, seed=seed)
    return user, chat_id


def test_clone_a_chat_with_files(tmp_path):
    juicefs = tmp_path / "juicefs"
    artifacts = juicefs / "artifacts"
    user, chat_id = _chat_with_files(artifacts)
    app = main_app(user)

    async def run():
        async with asgi_client(app) as client:
            async with LoopProbe() as probe:
                response = await client.post(f"/api/v1/chats/{chat_id}/clone", json={"title": "Copy"})
                assert response.status_code == 200, response.text
        return probe.stats

    with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts), db_delay(), fs_delay([juicefs]):
        stats = asyncio.run(run())
    record(f"chat files: clone a chat with {ENTRIES} files", stats)
    check_budget(stats, max_lag_ms=50, pending="#8 sandbox copy on clone")


def test_delete_a_chat_with_files(tmp_path):
    juicefs = tmp_path / "juicefs"
    artifacts = juicefs / "artifacts"
    user, chat_id = _chat_with_files(artifacts, seed=1)
    app = main_app(user)

    async def run():
        async with asgi_client(app) as client:
            async with LoopProbe() as probe:
                response = await client.delete(f"/api/v1/chats/{chat_id}")
                assert response.status_code == 200, response.text
        return probe.stats

    with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts), db_delay(), fs_delay([juicefs]):
        stats = asyncio.run(run())
    assert not (artifacts / chat_id).exists()
    record(f"chat files: delete a chat with {ENTRIES} files", stats)
    check_budget(stats, max_lag_ms=50, pending="#8 sandbox delete")
