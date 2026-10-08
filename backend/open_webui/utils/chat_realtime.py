"""Websocket fan-out for sidebar rows, artifact lists, and chat versions.

Streamed reply parts (status, usage, sources, files) are batched here. They
do not bump the revision watchers compare, and they do not emit
``chat:updated``.
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
# The client caches at most 16 chats plus the one on screen. Each id costs
# an access check, so a socket cannot ask for more than this.
MAX_WATCHED_CHATS = 20

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

# Streamed reply parts waiting to be written, per (chat, message).
_pending_updates: dict[tuple[str, str], dict] = {}
_update_tasks: dict[tuple[str, str], asyncio.Task] = {}
_artifact_tasks: dict[str, asyncio.Task] = {}
_artifact_dirty: set[str] = set()


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


def watcher_session_ids(chat_id: str | None) -> list[str]:
    """Sessions caching this chat, including the one that has it on screen."""
    if not chat_id:
        return []
    return list(WATCH_INDEX.get(chat_id) or [])


def _access_row(chat_id: str):
    row = Chats.get_chat_access_row(chat_id)
    if row is not None:
        return row
    return Chats.get_chat_by_id(chat_id)


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


async def emit_chat_list(
    chat, row: dict | None = None, *, previous_visibility: str | None = None
) -> None:
    payload = row or list_row(chat)
    await _emit_to_user(chat.user_id, "chat:list", payload)
    was_org = previous_visibility == "organization"
    is_org = getattr(chat, "visibility", None) == "organization"
    if not is_org and not was_org:
        return
    member_payload = (
        {**payload, "removed": True} if was_org and not is_org else payload
    )
    from open_webui.models.organizations import Organizations

    try:
        members = Organizations.get_members(chat.organization_id)
    except Exception:
        log.debug("organization members lookup failed", exc_info=True)
        return
    for member in members:
        user_id = getattr(member, "user_id", None)
        if user_id and user_id != chat.user_id:
            await _emit_to_user(user_id, "chat:list", member_payload)


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


async def publish_chat_committed(
    chat_id: str, previous_visibility: str | None = None
) -> None:
    chat = Chats.get_chat_by_id(chat_id)
    if chat is None:
        return
    row = list_row(chat)
    await emit_chat_list(chat, row, previous_visibility=previous_visibility)
    await emit_chat_updated(chat)


def schedule_chat_committed(
    chat_id: str, previous_visibility: str | None = None
) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _run():
        try:
            await publish_chat_committed(
                chat_id, previous_visibility=previous_visibility
            )
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
            drop_chat_watch(sid, chat.id)
        except Exception:
            log.debug("evict on delete failed", exc_info=True)


async def recheck_watches(user_id: str | None = None) -> None:
    """Re-run the subscribe-time access check after access changed.

    Stream events trust the watch index instead of checking access per
    event, so every action that can take read access away calls this:
    removing a member, deleting an organization, deleting a user. With a
    user id only that user's sessions are checked; without one, every
    session is. A chat that fails the check is dropped from the session's
    watch and the tab is told to evict it.
    """
    users: dict = {}
    rows: dict = {}
    for sid, watch in list(WATCHES.items()):
        owner_id = (watch or {}).get("user_id")
        if user_id is not None and owner_id != user_id:
            continue
        if owner_id not in users:
            users[owner_id] = Users.get_user_by_id(owner_id) if owner_id else None
        user = users[owner_id]
        chat_ids = list(dict.fromkeys([*(watch.get("ids") or []), watch.get("active")]))
        for chat_id in chat_ids:
            if not chat_id:
                continue
            if chat_id not in rows:
                rows[chat_id] = Chats.get_chat_access_row(chat_id)
            if user is not None and can_read_chat(user, rows[chat_id]):
                continue
            drop_chat_watch(sid, chat_id)
            try:
                await sio.emit("chat:evict", {"id": chat_id}, to=sid)
            except Exception:
                log.debug("chat evict failed", exc_info=True)


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
        _artifact_dirty.add(chat_id)
        return

    async def _run():
        try:
            while True:
                await asyncio.sleep(ARTIFACT_DEBOUNCE_SECONDS)
                from open_webui.utils.artifacts import list_artifacts

                files = await asyncio.to_thread(list_artifacts, chat_id)
                await emit_chat_artifacts(chat_id, files)
                if chat_id not in _artifact_dirty:
                    break
                _artifact_dirty.discard(chat_id)
        except Exception:
            log.debug("artifact emit failed", exc_info=True)
        finally:
            _artifact_tasks.pop(chat_id, None)
            _artifact_dirty.discard(chat_id)

    _artifact_tasks[chat_id] = loop.create_task(_run())


def schedule_message_update(chat_id: str, message_id: str, kind: str, data) -> None:
    """Queue one streamed reply part. Written within STATUS_FLUSH_SECONDS,
    or sooner as part of the reply's final save (save_final_reply)."""
    if not chat_id or chat_id == "local" or not message_id or data is None:
        return
    from open_webui.utils.message_updates import add_to_pending

    key = (chat_id, message_id)
    add_to_pending(_pending_updates.setdefault(key, {}), kind, data)
    task = _update_tasks.get(key)
    if task is not None and not task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        flush_message_updates_now(chat_id, message_id)
        return

    async def _later():
        try:
            await asyncio.sleep(STATUS_FLUSH_SECONDS)
            await asyncio.to_thread(flush_message_updates_now, chat_id, message_id)
        except asyncio.CancelledError:
            return
        except Exception:
            log.debug("message update flush failed", exc_info=True)

    _update_tasks[key] = loop.create_task(_later())


def flush_message_updates_now(chat_id: str, message_id: str) -> None:
    key = (chat_id, message_id)
    updates = _pending_updates.pop(key, None)
    _update_tasks.pop(key, None)
    if not updates:
        return
    Chats.merge_message_updates(chat_id, message_id, updates)


REPLY_SAVE_FAILED_MESSAGE = (
    "There was an error saving the response from the server. Please retry"
)
# Pauses between attempts at a reply's final save; one more attempt than pauses.
FINAL_SAVE_RETRY_SECONDS = (0.5, 2.0)


async def save_final_reply(chat_id: str, message_id: str, patch: dict) -> bool:
    """Save a finished reply, with its pending streamed parts, retrying a few times.

    Never raises. False means every attempt failed; the caller tells the user
    with REPLY_SAVE_FAILED_MESSAGE instead of reporting a failed generation.
    """
    if not chat_id or chat_id == "local" or not message_id:
        return True
    key = (chat_id, message_id)
    task = _update_tasks.pop(key, None)
    if task is not None and task is not asyncio.current_task() and not task.done():
        task.cancel()
    # Kept across attempts, so a failed attempt does not drop them.
    updates = _pending_updates.pop(key, None)
    attempts = len(FINAL_SAVE_RETRY_SECONDS) + 1
    for attempt in range(attempts):
        try:
            await asyncio.to_thread(
                Chats.save_reply, chat_id, message_id, patch, updates
            )
            return True
        except Exception:
            log.warning(
                "Saving reply failed (attempt %s of %s) chat_id=%s message_id=%s",
                attempt + 1,
                attempts,
                chat_id,
                message_id,
                exc_info=True,
            )
            if attempt < len(FINAL_SAVE_RETRY_SECONDS):
                await asyncio.sleep(FINAL_SAVE_RETRY_SECONDS[attempt])
    log.error(
        "Reply not saved after %s attempts chat_id=%s message_id=%s",
        attempts,
        chat_id,
        message_id,
    )
    return False


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
        candidates = [
            chat_id
            for chat_id in dict.fromkeys(
                item for item in requested if isinstance(item, str)
            )
            if chat_id and chat_id != "local"
        ]
        # The chat on screen is checked first so the cap never drops it.
        if isinstance(active, str) and active in candidates:
            candidates.remove(active)
            candidates.insert(0, active)
        allowed = []
        for chat_id in candidates[:MAX_WATCHED_CHATS]:
            chat = Chats.get_chat_access_row(chat_id)
            if can_read_chat(user, chat):
                allowed.append(chat_id)
        active_id = active if isinstance(active, str) and active in allowed else None
        set_watch(sid, user.id, allowed, active_id)
        return {"ids": allowed, "active": active_id}
