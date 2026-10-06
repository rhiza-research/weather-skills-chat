"""Websocket fan-out for sidebar rows, artifact lists, and chat versions.

Status-history writes are coalesced here. They do not bump the revision
watchers compare, and they do not emit ``chat:updated``.
"""

import asyncio
import logging
import time

from open_webui.env import (
    SRC_LOG_LEVELS,
    WEBSOCKET_MANAGER,
    WEBSOCKET_REDIS_URL,
    WEBSOCKET_SENTINEL_HOSTS,
    WEBSOCKET_SENTINEL_PORT,
)
from open_webui.models.chats import Chats
from open_webui.models.users import UserModel, Users
from open_webui.socket.main import SESSION_POOL, USER_POOL, sio
from open_webui.utils.organizations import can_read_chat
from open_webui.utils.redis import get_sentinels_from_env

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["SOCKET"])

STATUS_FLUSH_SECONDS = 2.0
ARTIFACT_DEBOUNCE_SECONDS = 0.4

if WEBSOCKET_MANAGER == "redis":
    from open_webui.socket.utils import RedisDict

    _sentinels = get_sentinels_from_env(WEBSOCKET_SENTINEL_HOSTS, WEBSOCKET_SENTINEL_PORT)
    WATCHES = RedisDict(
        "open-webui:chat_watches",
        redis_url=WEBSOCKET_REDIS_URL,
        redis_sentinels=_sentinels,
    )
    WATCH_INDEX = RedisDict(
        "open-webui:chat_watch_index",
        redis_url=WEBSOCKET_REDIS_URL,
        redis_sentinels=_sentinels,
    )
    ACTIVE_INDEX = RedisDict(
        "open-webui:chat_active_index",
        redis_url=WEBSOCKET_REDIS_URL,
        redis_sentinels=_sentinels,
    )
else:
    WATCHES = {}
    WATCH_INDEX = {}
    ACTIVE_INDEX = {}

_status_pending: dict[tuple[str, str], list] = {}
_status_tasks: dict[tuple[str, str], asyncio.Task] = {}
_artifact_tasks: dict[str, asyncio.Task] = {}


def chat_revision(chat) -> int:
    meta = getattr(chat, "meta", None) or {}
    if not isinstance(meta, dict):
        return 0
    try:
        return int(meta.get("revision") or 0)
    except (TypeError, ValueError):
        return 0


def touch_revision(chat_item) -> int:
    meta = dict(chat_item.meta or {})
    revision = int(meta.get("revision") or 0) + 1
    meta["revision"] = revision
    chat_item.meta = meta
    chat_item.updated_at = int(time.time())
    return revision


def list_row(chat) -> dict:
    owner = ""
    try:
        user = Users.get_user_by_id(chat.user_id)
        owner = user.name if user else ""
    except Exception:
        owner = ""
    return {
        "id": chat.id,
        "title": chat.title,
        "updated_at": chat.updated_at,
        "created_at": chat.created_at,
        "folder_id": chat.folder_id,
        "visibility": chat.visibility,
        "organization_id": chat.organization_id,
        "user_id": chat.user_id,
        "owner_name": owner,
        "pinned": bool(chat.pinned),
        "archived": bool(chat.archived),
        "revision": chat_revision(chat),
    }


def _user_for_sid(sid: str):
    session = SESSION_POOL.get(sid)
    if not session:
        return None
    if isinstance(session, dict) and session.get("id"):
        try:
            return UserModel.model_validate(session)
        except Exception:
            return Users.get_user_by_id(session["id"])
    return None


def _index_add(index, key: str, sid: str) -> None:
    current = list(index.get(key) or [])
    if sid not in current:
        current.append(sid)
        index[key] = current


def _index_remove(index, key: str, sid: str) -> None:
    current = [item for item in list(index.get(key) or []) if item != sid]
    if current:
        index[key] = current
    elif key in index:
        del index[key]


def clear_watch(sid: str) -> None:
    previous = WATCHES.get(sid)
    if not previous:
        return
    for chat_id in previous.get("ids") or []:
        _index_remove(WATCH_INDEX, chat_id, sid)
    if previous.get("active"):
        _index_remove(ACTIVE_INDEX, previous["active"], sid)
    if sid in WATCHES:
        del WATCHES[sid]


def drop_chat_watch(sid: str, chat_id: str) -> None:
    previous = WATCHES.get(sid)
    if not previous:
        _index_remove(WATCH_INDEX, chat_id, sid)
        _index_remove(ACTIVE_INDEX, chat_id, sid)
        return
    ids = [item for item in (previous.get("ids") or []) if item != chat_id]
    active = previous.get("active")
    if active == chat_id:
        active = None
    _index_remove(WATCH_INDEX, chat_id, sid)
    _index_remove(ACTIVE_INDEX, chat_id, sid)
    if ids or active:
        WATCHES[sid] = {"user_id": previous.get("user_id"), "ids": ids, "active": active}
    elif sid in WATCHES:
        del WATCHES[sid]


def set_watch(sid: str, user_id: str, chat_ids: list[str], active: str | None) -> None:
    clear_watch(sid)
    ids = list(dict.fromkeys(chat_ids))
    WATCHES[sid] = {"user_id": user_id, "ids": ids, "active": active}
    for chat_id in ids:
        _index_add(WATCH_INDEX, chat_id, sid)
    if active:
        _index_add(ACTIVE_INDEX, active, sid)


def active_session_ids(chat_id: str | None) -> list[str]:
    if not chat_id:
        return []
    return list(ACTIVE_INDEX.get(chat_id) or [])


def watcher_session_ids(chat_id: str | None) -> list[str]:
    """Sessions caching this chat, including the one that has it on screen."""
    if not chat_id:
        return []
    return list(WATCH_INDEX.get(chat_id) or [])


def _access_row(chat_id: str):
    chat = Chats.get_chat_by_id(chat_id)
    if chat is None:
        return None
    return chat


async def _emit_if_allowed(sid: str, chat, event: str, payload: dict) -> bool:
    user = _user_for_sid(sid)
    if user is None or not can_read_chat(user, chat):
        drop_chat_watch(sid, chat.id)
        try:
            await sio.emit("chat:evict", {"id": chat.id}, to=sid)
        except Exception:
            log.debug("chat evict failed", exc_info=True)
        return False
    await sio.emit(event, payload, to=sid)
    return True


async def _emit_to_user(user_id: str, event: str, payload: dict) -> None:
    if not user_id:
        return
    for sid in list(USER_POOL.get(user_id) or []):
        try:
            await sio.emit(event, payload, to=sid)
        except Exception:
            log.debug("emit to user failed", exc_info=True)


async def emit_chat_list(chat, row: dict | None = None) -> None:
    payload = row or list_row(chat)
    await _emit_to_user(chat.user_id, "chat:list", payload)
    if getattr(chat, "visibility", None) != "organization":
        return
    from open_webui.models.organizations import Organizations

    try:
        members = Organizations.get_members(chat.organization_id)
    except Exception:
        log.debug("organization members lookup failed", exc_info=True)
        return
    for member in members:
        user_id = getattr(member, "user_id", None)
        if user_id and user_id != chat.user_id:
            await _emit_to_user(user_id, "chat:list", payload)


async def emit_chat_updated(chat) -> None:
    payload = {
        "id": chat.id,
        "updated_at": chat.updated_at,
        "revision": chat_revision(chat),
    }
    for sid in list(WATCH_INDEX.get(chat.id) or []):
        try:
            await _emit_if_allowed(sid, chat, "chat:updated", payload)
        except Exception:
            log.debug("chat:updated failed", exc_info=True)
    await _emit_to_user(chat.user_id, "chat:updated", payload)


async def emit_chat_turn(
    user_id: str,
    chat_id: str,
    session_id: str | None,
    user_message: dict | None,
    assistant_message: dict | None,
) -> None:
    """Tell subscribers the new user and assistant messages. No document fetch."""
    assistant_id = (assistant_message or {}).get("id")
    if not chat_id or not assistant_id:
        return
    from open_webui.socket.main import get_event_emitter

    emitter = get_event_emitter(
        {
            "user_id": user_id,
            "chat_id": chat_id,
            "message_id": assistant_id,
            "session_id": session_id,
        },
        update_db=False,
    )
    await emitter(
        {
            "type": "chat:turn",
            "data": {
                "user_message": user_message,
                "assistant_message": assistant_message,
            },
        }
    )


async def publish_chat_committed(chat_id: str) -> None:
    chat = Chats.get_chat_by_id(chat_id)
    if chat is None:
        return
    row = list_row(chat)
    await emit_chat_list(chat, row)
    await emit_chat_updated(chat)


def schedule_chat_committed(chat_id: str) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run():
        try:
            await publish_chat_committed(chat_id)
        except Exception:
            log.debug("publish chat failed", exc_info=True)

    loop.create_task(_run())


async def publish_chat_removed(chat) -> None:
    row = list_row(chat)
    row["removed"] = True
    await emit_chat_list(chat, row)
    for sid in list(WATCH_INDEX.get(chat.id) or []):
        try:
            await sio.emit("chat:evict", {"id": chat.id}, to=sid)
            clear_watch(sid)
        except Exception:
            log.debug("evict on delete failed", exc_info=True)


async def emit_chat_artifacts(chat_id: str, files: list) -> None:
    chat = _access_row(chat_id)
    if chat is None:
        return
    payload = {"id": chat_id, "files": files}
    seen = set()
    for sid in list(WATCH_INDEX.get(chat_id) or []) + list(USER_POOL.get(chat.user_id) or []):
        if sid in seen:
            continue
        seen.add(sid)
        try:
            await _emit_if_allowed(sid, chat, "chat:artifacts", payload)
        except Exception:
            log.debug("chat:artifacts failed", exc_info=True)


def schedule_artifacts(chat_id: str) -> None:
    if not chat_id or chat_id == "local":
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    existing = _artifact_tasks.get(chat_id)
    if existing and not existing.done():
        return

    async def _run():
        try:
            await asyncio.sleep(ARTIFACT_DEBOUNCE_SECONDS)
            from open_webui.utils.artifacts import list_artifacts

            files = await asyncio.to_thread(list_artifacts, chat_id)
            await emit_chat_artifacts(chat_id, files)
        except Exception:
            log.debug("artifact emit failed", exc_info=True)
        finally:
            _artifact_tasks.pop(chat_id, None)

    _artifact_tasks[chat_id] = loop.create_task(_run())


def schedule_status(chat_id: str, message_id: str, status: dict) -> None:
    if not chat_id or not message_id or not isinstance(status, dict):
        return
    key = (chat_id, message_id)
    _status_pending.setdefault(key, []).append(status)
    task = _status_tasks.get(key)
    if task is not None and not task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        flush_statuses_now(chat_id, message_id)
        return

    async def _later():
        try:
            await asyncio.sleep(STATUS_FLUSH_SECONDS)
            await asyncio.to_thread(flush_statuses_now, chat_id, message_id)
        except asyncio.CancelledError:
            return
        except Exception:
            log.debug("status flush failed", exc_info=True)

    _status_tasks[key] = loop.create_task(_later())


def flush_statuses_now(chat_id: str, message_id: str) -> None:
    key = (chat_id, message_id)
    batch = _status_pending.pop(key, [])
    _status_tasks.pop(key, None)
    if not batch:
        return
    Chats.append_message_statuses(chat_id, message_id, batch)


async def flush_statuses(chat_id: str, message_id: str) -> None:
    key = (chat_id, message_id)
    task = _status_tasks.get(key)
    if task is not None and task is not asyncio.current_task() and not task.done():
        task.cancel()
    await asyncio.to_thread(flush_statuses_now, chat_id, message_id)


def register() -> None:
    @sio.on("chat:watch")
    async def chat_watch(sid, data):
        user = _user_for_sid(sid)
        if user is None:
            return {"ids": []}
        requested = data.get("ids") if isinstance(data, dict) else []
        if not isinstance(requested, list):
            requested = []
        active = data.get("active") if isinstance(data, dict) else None
        allowed = []
        for chat_id in requested:
            if not isinstance(chat_id, str) or not chat_id or chat_id == "local":
                continue
            chat = Chats.get_chat_by_id(chat_id)
            if can_read_chat(user, chat):
                allowed.append(chat_id)
        active_id = active if isinstance(active, str) and active in allowed else None
        set_watch(sid, user.id, allowed, active_id)
        return {"ids": allowed, "active": active_id}
