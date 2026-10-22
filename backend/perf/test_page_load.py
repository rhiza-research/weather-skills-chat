"""Page load (#17, and #5 where routes return whole chats).

On load the browser fetches about 19 routes at once: the chat list, recent
chats, pinned chats, folders, tags, models, tools, skills, secrets,
organizations, usage, settings and config. Most are async handlers that call
the database synchronously and await nothing, so each query holds the event
loop; pinned chats and folders also load whole chat documents.

Routes are the ones prod served on page load (request counts, 2026-10-21).
"""

import asyncio

from perf_harness import LoopProbe, check_budget, db_delay, record
from perf_harness.app_data import asgi_client, ensure_user, insert_chat, main_app
from perf_harness.data import big_chat

PAGE_LOAD_ROUTES = [
    "/api/v1/chats/?page=1",
    "/api/v1/chats/recent",
    "/api/v1/chats/pinned",
    "/api/v1/chats/all/tags",
    "/api/v1/folders/",
    "/api/models",
    "/api/v1/models/",
    "/api/v1/tools/",
    "/api/v1/tool_summary",
    "/api/v1/skills/",
    "/api/v1/secrets/",
    "/api/v1/automations/",
    "/api/v1/organizations/",
    "/api/v1/usage/me",
    "/api/v1/users/user/settings",
    "/api/v1/user_config",
    "/api/app_config",
    "/api/v1/configs/banners",
    "/api/v1/auths/",
]
CHATS = 60
LARGE_CHATS = 8  # long agent conversations, 1.5 MB each
TABS = 3  # page loads at once: tabs opened together, or a reconnect


def _account():
    from open_webui.models.chats import Chats
    from open_webui.models.folders import Folders

    user = ensure_user("perf-page-user")
    chat_ids = []
    for i in range(CHATS):
        size = 1_500_000 if i < LARGE_CHATS else 30_000
        chat_ids.append(insert_chat(user.id, big_chat(size)))
    folders = [Folders.insert_new_folder(user.id, f"Project {i}") for i in range(4)]
    for i, chat_id in enumerate(chat_ids[:12]):
        Chats.update_chat_folder_id_by_id_and_user_id(chat_id, user.id, folders[i % 4].id)
    for chat_id in chat_ids[2:6]:
        Chats.toggle_chat_pinned_by_id(chat_id)
    for i, chat_id in enumerate(chat_ids[:30]):
        Chats.add_chat_tag_by_id_and_user_id_and_tag_name(chat_id, user.id, f"region-{i % 5}")
    return user


def test_page_load(tmp_path):
    user = _account()
    app = main_app(user)

    async def run():
        async with asgi_client(app) as client:
            async with LoopProbe() as probe:
                responses = await asyncio.gather(
                    *(client.get(route) for _ in range(TABS) for route in PAGE_LOAD_ROUTES)
                )
        failed = [(r.request.url.path, r.status_code) for r in responses if r.status_code != 200]
        assert not failed, failed
        return probe.stats

    with db_delay():
        stats = asyncio.run(run())
    record(f"page load: {len(PAGE_LOAD_ROUTES)} routes in {TABS} tabs, {CHATS} chats", stats)
    check_budget(stats, max_lag_ms=25, blocked_pct=20, pending="#17 async handlers that never await, #5 whole-chat responses")
