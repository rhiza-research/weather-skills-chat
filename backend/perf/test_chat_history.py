"""Saving chat edits (#3): POST /api/v1/chats/{id}/history.

The browser saves message edits and new messages as history patches. Each
patch locks the chat row (waiting up to 3 s for another writer), merges the
patch into the whole chat document and writes it back, on the event loop. The
route then returns the whole updated chat (#5).
"""

import asyncio
import time

from perf_harness import LoopProbe, check_budget, db_delay, record
from perf_harness.app_data import asgi_client, ensure_user, insert_chat, main_app
from perf_harness.data import big_chat

PATCHES = 30
# Time between saves while someone types and the reply streams.
GAP_S = 0.01


def test_history_patches_on_a_large_chat(tmp_path):
    user = ensure_user()
    chat_id = insert_chat(user.id, big_chat(1_500_000))
    app = main_app(user)

    async def run():
        async with asgi_client(app) as client:
            chat = (await client.get(f"/api/v1/chats/{chat_id}")).json()
            revision = (chat.get("meta") or {}).get("revision")
            parent = chat["chat"]["history"]["currentId"]
            async with LoopProbe() as probe:
                for i in range(PATCHES):
                    message = {
                        "id": f"edit-{i}",
                        "parentId": parent,
                        "childrenIds": [],
                        "role": "user",
                        "content": f"Follow-up question {i} about weekly rainfall totals.",
                        "timestamp": int(time.time()),
                    }
                    body = {"upsert": {f"edit-{i}": message}, "delete": []}
                    if revision is not None:
                        body["expected_revision"] = revision
                    response = await client.post(f"/api/v1/chats/{chat_id}/history", json=body)
                    assert response.status_code == 200, response.text
                    # The route returns the whole updated chat.
                    revision = ((response.json() or {}).get("meta") or {}).get("revision", revision)
                    await asyncio.sleep(GAP_S)
        return probe.stats

    with db_delay():
        stats = asyncio.run(run())
    record(f"chat history: {PATCHES} patches on a 1.5 MB chat", stats)
    check_budget(stats, max_lag_ms=25, blocked_pct=10, pending="#3 apply_history_patch, #5 whole-chat responses")
