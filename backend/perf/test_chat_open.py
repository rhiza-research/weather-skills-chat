"""Opening and acting on a large chat (#5, #6).

Opening a chat fetches the chat itself, its tags, its running tasks, its tool
runner and its files at once. Several of these load the whole chat; routes
that return it have FastAPI validate and serialize it on the event loop (#5),
and every full load also JSON-encodes the chat once more just to log its size
(#6). Chat actions such as pin and archive return the whole chat too.
"""

import asyncio

from perf_harness import LoopProbe, check_budget, db_delay, record
from perf_harness.app_data import asgi_client, ensure_user, insert_chat, main_app
from perf_harness.data import big_chat

OPENS = 10
ACTIONS = 30


def test_open_a_large_chat(tmp_path):
    user = ensure_user()
    chat_ids = [insert_chat(user.id, big_chat(1_500_000)) for _ in range(OPENS)]
    app = main_app(user)

    async def run():
        async with asgi_client(app) as client:
            async with LoopProbe() as probe:
                for chat_id in chat_ids:
                    responses = await asyncio.gather(
                        client.get(f"/api/v1/chats/{chat_id}"),
                        client.get(f"/api/v1/chats/{chat_id}/tags"),
                        client.get(f"/api/tasks/chat/{chat_id}"),
                    )
                    assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]
                    await asyncio.sleep(0.05)  # reading the chat before opening the next
        return probe.stats

    with db_delay():
        stats = asyncio.run(run())
    record(f"chat open: {OPENS} opens of a 1.5 MB chat", stats)
    check_budget(stats, max_lag_ms=25, blocked_pct=10, pending="#5 whole-chat responses, #6 chat load logging")


def test_pin_and_archive_a_large_chat(tmp_path):
    user = ensure_user()
    chat_id = insert_chat(user.id, big_chat(1_500_000))
    app = main_app(user)

    async def run():
        async with asgi_client(app) as client:
            async with LoopProbe() as probe:
                for i in range(ACTIONS):
                    action = "pin" if i % 2 == 0 else "archive"
                    response = await client.post(f"/api/v1/chats/{chat_id}/{action}")
                    assert response.status_code == 200, response.text
        return probe.stats

    with db_delay():
        stats = asyncio.run(run())
    record(f"chat actions: {ACTIONS} pin and archive toggles on a 1.5 MB chat", stats)
    check_budget(stats, max_lag_ms=10, blocked_pct=10, pending="#5 whole-chat responses, #6 chat load logging")
