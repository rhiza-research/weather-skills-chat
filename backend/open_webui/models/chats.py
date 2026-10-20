import logging
import json
import threading
from contextlib import contextmanager
import time
import uuid
from typing import Optional

from open_webui.internal.db import Base, get_db
from open_webui.models.tags import TagModel, Tag, Tags
from open_webui.env import SRC_LOG_LEVELS

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Boolean, Column, String, Text, JSON
from sqlalchemy import or_, func, select, and_, text
from sqlalchemy.sql import exists

####################
# Chat DB Schema
####################

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


class Chat(Base):
    __tablename__ = "chat"

    id = Column(String, primary_key=True)
    user_id = Column(String)
    title = Column(Text)
    chat = Column(JSON)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)

    share_id = Column(Text, unique=True, nullable=True)
    archived = Column(Boolean, default=False)
    pinned = Column(Boolean, default=False, nullable=True)

    meta = Column(JSON, server_default="{}")
    folder_id = Column(Text, nullable=True)
    organization_id = Column(Text, nullable=False)
    visibility = Column(Text, nullable=False, default="private")


class ChatModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    chat: dict

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    share_id: Optional[str] = None
    archived: bool = False
    pinned: Optional[bool] = False

    meta: dict = {}
    folder_id: Optional[str] = None
    organization_id: Optional[str] = None
    visibility: str = "private"


class ChatAccessRow(BaseModel):
    id: str
    user_id: str
    organization_id: Optional[str] = None
    visibility: str = "private"


CHAT_CONFLICT_MESSAGE = "Another user has edited the chat. Please try again."
CHAT_BUSY_MESSAGE = (
    "This chat is being edited by another window. Please try again shortly."
)
CHAT_SAVE_FAILED_MESSAGE = "The chat could not be saved. Please try again."


class ChatWriteError(Exception):
    def __init__(self, message: str, *, busy: bool = False):
        super().__init__(message)
        self.message = message
        self.busy = busy


# How long a chat write waits for another write to the same chat to finish.
# A save from the browser fails fast with "busy" so the user can try again; a
# save the server makes for itself (a reply, its status, its title) waits
# longer. Writes run in worker threads, so waiting never stalls the server.
BROWSER_WRITE_WAIT_S = 3.0
SERVER_WRITE_WAIT_S = 15.0

# How writes to one chat take turns depends on the database:
# - Postgres: the row lock (SELECT ... FOR UPDATE). It holds across every
#   process and pod, so nothing in this process is involved.
# - SQLite: there is no row lock, so writes take turns on these in-process
#   locks. That is only correct with a single app process, which is the only
#   way SQLite is supported.
_CHAT_WRITE_LOCKS = tuple(threading.RLock() for _ in range(64))


def _chat_write_lock(chat_id: str):
    return _CHAT_WRITE_LOCKS[hash(chat_id) % len(_CHAT_WRITE_LOCKS)]


####################
# Forms
####################


class ChatForm(BaseModel):
    chat: dict
    organization_id: Optional[str] = None
    visibility: Optional[str] = None


class ChatImportForm(ChatForm):
    meta: Optional[dict] = {}
    pinned: Optional[bool] = False
    folder_id: Optional[str] = None


class ChatTitleMessagesForm(BaseModel):
    title: str
    messages: list[dict]


class ChatTitleForm(BaseModel):
    title: str


class ChatResponse(BaseModel):
    id: str
    user_id: str
    title: str
    chat: dict
    updated_at: int  # timestamp in epoch
    created_at: int  # timestamp in epoch
    share_id: Optional[str] = None  # id of the chat to be shared
    archived: bool
    pinned: Optional[bool] = False
    meta: dict = {}
    folder_id: Optional[str] = None
    organization_id: Optional[str] = None
    visibility: str = "private"


class ChatTitleIdResponse(BaseModel):
    id: str
    title: str
    updated_at: int
    created_at: int
    organization_id: Optional[str] = None
    visibility: Optional[str] = None
    user_id: Optional[str] = None
    owner_name: Optional[str] = None


def _chat_visible_filter(user_id: str, organization_id: str):
    return and_(
        Chat.organization_id == organization_id,
        or_(
            Chat.visibility == "organization",
            Chat.user_id == user_id,
        ),
    )


class ChatTable:

    @staticmethod
    def _has_row_locks(db) -> bool:
        dialect = getattr(getattr(db, "bind", None), "dialect", None)
        return dialect is not None and dialect.name == "postgresql"

    def _lock_chat_row(self, db, id: str, wait_s: float):
        if self._has_row_locks(db):
            db.execute(text(f"SET LOCAL lock_timeout = '{int(wait_s * 1000)}ms'"))
            return (
                db.query(Chat).filter(Chat.id == id).with_for_update().first()
            )
        return db.get(Chat, id)

    @contextmanager
    def _locked_chat(self, id: str, wait_s: float = BROWSER_WRITE_WAIT_S):
        """A session holding this chat for writing: (db, chat row or None).

        Call it from a worker thread, never from the event loop: it can wait
        up to ``wait_s`` for another write to the same chat.
        """
        with get_db() as db:
            if self._has_row_locks(db):
                yield db, self._lock_chat_row(db, id, wait_s)
                return
            lock = _chat_write_lock(id)
            if not lock.acquire(timeout=wait_s):
                raise ChatWriteError(CHAT_BUSY_MESSAGE, busy=True)
            try:
                yield db, self._lock_chat_row(db, id, wait_s)
            finally:
                lock.release()

    def _write_locked_chat(
        self,
        id: str,
        apply,
        *,
        expected_revision: Optional[int] = None,
        bump_revision: bool = True,
        check_revision: bool = False,
        wait_s: float = SERVER_WRITE_WAIT_S,
    ) -> tuple[Optional[ChatModel], str]:
        from sqlalchemy.exc import OperationalError

        from open_webui.utils.chat_realtime import chat_revision

        try:
            with self._locked_chat(id, wait_s) as (db, chat_item):
                if chat_item is None:
                    return None, "missing"
                current = chat_revision(chat_item)
                if (
                    check_revision
                    and expected_revision is not None
                    and int(expected_revision) != current
                ):
                    return ChatModel.model_validate(chat_item), "conflict"
                chat = json.loads(json.dumps(chat_item.chat or {}))
                result = apply(chat, chat_item)
                if result is None:
                    return ChatModel.model_validate(chat_item), "ok"
                new_chat, changed = result
                if not changed:
                    return ChatModel.model_validate(chat_item), "ok"
                chat_item.chat = new_chat
                if isinstance(new_chat, dict) and "title" in new_chat:
                    chat_item.title = new_chat["title"]
                if bump_revision:
                    self._touch_visible(chat_item)
                db.commit()
                db.refresh(chat_item)
                model = ChatModel.model_validate(chat_item)
            if bump_revision:
                self._schedule_visible_commit(id)
            return model, "ok"
        except OperationalError as exc:
            log.exception("chat write lock failed")
            raise ChatWriteError(CHAT_BUSY_MESSAGE, busy=True) from exc
        except ChatWriteError:
            raise
        except Exception as exc:
            log.exception("chat write failed")
            raise ChatWriteError(CHAT_SAVE_FAILED_MESSAGE) from exc

    def get_chat_revision(self, id: str) -> int:
        """The chat's revision, read from ``meta`` alone. 0 when the chat is gone."""
        from open_webui.utils.chat_realtime import chat_revision
        from types import SimpleNamespace

        with get_db() as db:
            meta = db.query(Chat.meta).filter(Chat.id == id).scalar()
        return chat_revision(SimpleNamespace(meta=meta))

    def get_chat_access_row(self, id: str) -> Optional[ChatAccessRow]:
        from sqlalchemy.orm import defer, load_only

        with get_db() as db:
            chat = (
                db.query(Chat)
                .options(
                    load_only(
                        Chat.id, Chat.user_id, Chat.organization_id, Chat.visibility
                    ),
                    defer(Chat.chat),
                )
                .filter(Chat.id == id)
                .first()
            )
            if chat is None:
                return None
            return ChatAccessRow(
                id=chat.id,
                user_id=chat.user_id,
                organization_id=chat.organization_id,
                visibility=chat.visibility or "private",
            )

    def insert_new_chat(self, user_id: str, form_data: ChatForm) -> Optional[ChatModel]:
        from open_webui.utils.chat_timing import log_timing

        t0 = time.perf_counter()
        organization_id = form_data.organization_id or user_id
        visibility = form_data.visibility or "private"
        if organization_id == user_id:
            visibility = "private"
        with get_db() as db:
            id = str(uuid.uuid4())
            chat = ChatModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    "title": (
                        form_data.chat["title"]
                        if "title" in form_data.chat
                        else "New Chat"
                    ),
                    "chat": form_data.chat,
                    "organization_id": organization_id,
                    "visibility": visibility,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                    "meta": {"revision": 1},
                }
            )

            result = Chat(**chat.model_dump())
            db.add(result)
            db.commit()
            db.refresh(result)
            db_s = time.perf_counter() - t0
            juice_s = None
            if result:
                try:
                    from open_webui.utils.artifacts import chat_sandbox

                    t_fs = time.perf_counter()
                    chat_sandbox(result.id)
                    juice_s = time.perf_counter() - t_fs
                except Exception:
                    pass
            log_timing(
                "db.Chats.insert_new_chat",
                time.perf_counter() - t0,
                chat_id=getattr(result, "id", None),
                db_s=f"{db_s:.3f}",
                juicefs_sandbox_s=f"{juice_s:.3f}" if juice_s is not None else None,
                chat_json_bytes=len(json.dumps(form_data.chat or {}, default=str)),
            )
            created = ChatModel.model_validate(result) if result else None
            if created:
                self._schedule_visible_commit(created.id)
            return created

    def import_chat(
        self, user_id: str, form_data: ChatImportForm
    ) -> Optional[ChatModel]:
        with get_db() as db:
            id = str(uuid.uuid4())
            chat = ChatModel(
                **{
                    "id": id,
                    "user_id": user_id,
                    "title": (
                        form_data.chat["title"]
                        if "title" in form_data.chat
                        else "New Chat"
                    ),
                    "chat": form_data.chat,
                    "meta": form_data.meta,
                    "pinned": form_data.pinned,
                    "folder_id": form_data.folder_id,
                    "organization_id": form_data.organization_id or user_id,
                    "visibility": (
                        "private"
                        if (form_data.organization_id or user_id) == user_id
                        else (form_data.visibility or "private")
                    ),
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            result = Chat(**chat.model_dump())
            db.add(result)
            db.commit()
            db.refresh(result)
            if result:
                try:
                    from open_webui.utils.artifacts import chat_sandbox

                    chat_sandbox(result.id)
                except Exception:
                    pass
            return ChatModel.model_validate(result) if result else None

    def _schedule_visible_commit(
        self, chat_id: str, previous_visibility: str | None = None
    ) -> None:
        try:
            from open_webui.utils.chat_realtime import schedule_chat_committed

            schedule_chat_committed(chat_id, previous_visibility=previous_visibility)
        except Exception:
            log.debug("schedule chat commit failed", exc_info=True)

    def _touch_visible(self, chat_item) -> None:
        from open_webui.utils.chat_realtime import touch_revision

        touch_revision(chat_item)

    def update_chat_by_id(
        self, id: str, chat: dict, *, bump_revision: bool = True
    ) -> Optional[ChatModel]:
        from open_webui.utils.chat_timing import log_timing

        t0 = time.perf_counter()

        def apply(_current, _item):
            return chat, True

        result, state = self._write_locked_chat(
            id, apply, bump_revision=bump_revision, check_revision=False
        )
        log_timing(
            "db.Chats.update_chat_by_id",
            time.perf_counter() - t0,
            chat_id=id,
            chat_json_bytes=len(json.dumps(chat or {}, default=str)),
        )
        if state == "missing":
            return None
        return result

    def set_chat_times(
        self, id: str, created_at: int, updated_at: int
    ) -> Optional[ChatModel]:
        """Stamp timestamps without a visible commit (used by e2e fixtures)."""
        with self._locked_chat(id) as (db, chat_item):
            if chat_item is None:
                return None
            chat_item.created_at = created_at
            chat_item.updated_at = updated_at
            db.commit()
            db.refresh(chat_item)
            return ChatModel.model_validate(chat_item)

    def update_chat_fields(
        self,
        id: str,
        fields: dict,
        *,
        bump_revision: bool = True,
        wait_s: float = BROWSER_WRITE_WAIT_S,
    ) -> Optional[ChatModel]:
        """Set top-level fields of the stored chat, keeping everything else.

        The merge happens on the copy read under the lock, so a reply saved a
        moment earlier is not erased.
        """

        def apply(current, _item):
            return {**current, **(fields or {})}, True

        result, state = self._write_locked_chat(
            id, apply, bump_revision=bump_revision, wait_s=wait_s
        )
        return None if state == "missing" else result

    def update_chat_title_by_id(self, id: str, title: str) -> Optional[ChatModel]:
        # Title is sidebar metadata. It must not move the transcript revision
        # the next turn sends, or a follow-up races this write.
        return self.update_chat_fields(
            id, {"title": title}, bump_revision=False, wait_s=SERVER_WRITE_WAIT_S
        )

    def update_chat_tags_by_id(
        self, id: str, tags: list[str], user
    ) -> Optional[ChatModel]:
        chat = self.get_chat_by_id(id)
        if chat is None:
            return None

        self.delete_all_tags_by_id_and_user_id(id, user.id)

        for tag in chat.meta.get("tags", []):
            if self.count_chats_by_tag_name_and_user_id(tag, user.id) == 0:
                Tags.delete_tag_by_name_and_user_id(tag, user.id)

        for tag_name in tags:
            if tag_name.lower() == "none":
                continue

            self.add_chat_tag_by_id_and_user_id_and_tag_name(id, user.id, tag_name)
        return self.get_chat_by_id(id)

    def get_chat_title_by_id(self, id: str) -> Optional[str]:
        chat = self.get_chat_by_id(id)
        if chat is None:
            return None

        return chat.chat.get("title", "New Chat")

    def get_messages_by_chat_id(self, id: str) -> Optional[dict]:
        chat = self.get_chat_by_id(id)
        if chat is None:
            return None

        return chat.chat.get("history", {}).get("messages", {}) or {}

    def get_message_by_id_and_message_id(
        self, id: str, message_id: str
    ) -> Optional[dict]:
        chat = self.get_chat_by_id(id)
        if chat is None:
            return None

        return chat.chat.get("history", {}).get("messages", {}).get(message_id, {})

    def upsert_message_to_chat_by_id_and_message_id(
        self,
        id: str,
        message_id: str,
        message: dict,
        *,
        bump_revision: bool = True,
        wait_s: float = SERVER_WRITE_WAIT_S,
    ) -> Optional[ChatModel]:
        def apply(chat, _item):
            history = chat.get("history", {})
            messages = history.get("messages", {})
            if message_id in messages:
                messages[message_id] = {
                    **messages[message_id],
                    **message,
                }
            else:
                messages[message_id] = message
            history["messages"] = messages
            history["currentId"] = message_id
            chat["history"] = history
            return chat, True

        result, state = self._write_locked_chat(
            id, apply, bump_revision=bump_revision, check_revision=False, wait_s=wait_s
        )
        return None if state == "missing" else result

    def append_message_content(
        self, id: str, message_id: str, text: str
    ) -> Optional[ChatModel]:
        """Add text to the end of a stored message, read and written under the lock."""

        def apply(chat, _item):
            history = chat.get("history", {})
            messages = history.get("messages", {})
            message = messages.get(message_id)
            if not isinstance(message, dict) or not text:
                return chat, False
            messages[message_id] = {
                **message,
                "content": f"{message.get('content') or ''}{text}",
            }
            history["messages"] = messages
            chat["history"] = history
            return chat, True

        result, state = self._write_locked_chat(id, apply, bump_revision=False)
        return None if state == "missing" else result

    def save_reply(
        self, id: str, message_id: str, patch: dict, updates: Optional[dict] = None
    ) -> Optional[ChatModel]:
        """The final save of a reply: its pending streamed parts and its text
        in one write. Raises ChatWriteError when the chat cannot be written."""
        from open_webui.utils.message_updates import apply_to_message

        def apply(chat, _item):
            history = chat.get("history", {})
            messages = history.get("messages", {})
            current = messages.get(message_id)
            base = current if isinstance(current, dict) else {}
            if updates:
                base = apply_to_message(base, updates)
            messages[message_id] = {**base, **patch}
            history["messages"] = messages
            history["currentId"] = message_id
            chat["history"] = history
            return chat, True

        result, state = self._write_locked_chat(id, apply)
        return None if state == "missing" else result

    def merge_message_updates(
        self, id: str, message_id: str, updates: dict
    ) -> Optional[ChatModel]:
        """Write a batch of streamed reply parts into the stored message.

        The row is re-read under its lock, so content written since the batch
        was collected is kept. Does not move the watcher revision.
        """
        if not updates:
            return self.get_chat_by_id(id)
        from open_webui.utils.message_updates import apply_to_message

        def apply(chat, _item):
            history = chat.get("history", {})
            messages = history.get("messages", {})
            message = messages.get(message_id)
            if not isinstance(message, dict):
                return chat, False
            messages[message_id] = apply_to_message(message, updates)
            history["messages"] = messages
            chat["history"] = history
            return chat, True

        result, state = self._write_locked_chat(
            id, apply, bump_revision=False, check_revision=False
        )
        return None if state == "missing" else result

    def add_message_status_to_chat_by_id_and_message_id(
        self, id: str, message_id: str, status: dict
    ) -> Optional[ChatModel]:
        return self.merge_message_updates(
            id, message_id, {"status": status} if status else {}
        )

    def append_turn(
        self,
        id: str,
        user_message: dict,
        assistant_message: dict,
        expected_revision: Optional[int],
    ) -> tuple[Optional[ChatModel], str]:
        """Insert the client-minted user and assistant messages if they are new.

        Returns ``(chat, "ok" | "conflict" | "missing" | "error")``. A conflict
        leaves the row unchanged.
        """

        def apply(chat, _item):
            history = chat.get("history") or {}
            messages = history.get("messages") or {}
            user_id = user_message.get("id")
            assistant_id = assistant_message.get("id")
            parent_id = user_message.get("parentId")
            if parent_id and parent_id not in messages:
                raise ChatWriteError("The parent message for this turn is missing.")
            changed = False

            if user_id and user_id not in messages:
                stored_user = dict(user_message)
                children = list(stored_user.get("childrenIds") or [])
                if assistant_id and assistant_id not in children:
                    children.append(assistant_id)
                stored_user["childrenIds"] = children
                stored_user.setdefault("role", "user")
                messages[user_id] = stored_user
                changed = True
                if parent_id:
                    parent = dict(messages[parent_id])
                    parent_children = list(parent.get("childrenIds") or [])
                    if user_id not in parent_children:
                        parent_children.append(user_id)
                        parent["childrenIds"] = parent_children
                        messages[parent_id] = parent
            elif user_id and user_id in messages:
                stored_user = dict(messages[user_id])
                incoming_content = user_message.get("content")
                if incoming_content and incoming_content != stored_user.get("content"):
                    stored_user["content"] = incoming_content
                    changed = True
                if user_message.get("files"):
                    stored_user["files"] = user_message.get("files")
                    changed = True
                if assistant_id:
                    children = list(stored_user.get("childrenIds") or [])
                    if assistant_id not in children:
                        children.append(assistant_id)
                        stored_user["childrenIds"] = children
                        changed = True
                messages[user_id] = stored_user

            if assistant_id and assistant_id not in messages:
                stored_assistant = dict(assistant_message)
                stored_assistant.setdefault("role", "assistant")
                stored_assistant.setdefault("content", "")
                stored_assistant.setdefault("childrenIds", [])
                stored_assistant["parentId"] = user_id
                messages[assistant_id] = stored_assistant
                changed = True

            if assistant_id and history.get("currentId") != assistant_id:
                history["currentId"] = assistant_id
                changed = True
            if not changed:
                return chat, False
            history["messages"] = messages
            chat["history"] = history
            return chat, True

        try:
            return self._write_locked_chat(
                id,
                apply,
                expected_revision=expected_revision,
                check_revision=True,
                wait_s=BROWSER_WRITE_WAIT_S,
            )
        except ChatWriteError as exc:
            if "parent message" in str(exc).lower():
                return self.get_chat_by_id(id), "invalid"
            return None, "error"

    def apply_history_patch(
        self,
        id: str,
        upsert: dict,
        delete_ids: list,
        expected_revision: Optional[int],
    ) -> tuple[Optional[ChatModel], str]:
        """Merge a few messages into the stored tree."""

        def apply(chat, _item):
            history = chat.get("history") or {}
            messages = history.get("messages") or {}
            delete_set = set(delete_ids or [])
            current_id = history.get("currentId")
            deleted = {
                message_id: messages.pop(message_id, None) or {}
                for message_id in delete_set
            }
            for message in messages.values():
                if isinstance(message, dict) and message.get("childrenIds"):
                    message["childrenIds"] = [
                        child
                        for child in message.get("childrenIds") or []
                        if child not in delete_set
                    ]
            if current_id in delete_set:
                # Deleting a user message also deletes its replies, and the
                # current message is usually one of them. Climb past every
                # deleted message to the nearest one that is still stored.
                cursor = current_id
                seen = set()
                while cursor in deleted and cursor not in seen:
                    seen.add(cursor)
                    cursor = deleted[cursor].get("parentId")
                history["currentId"] = cursor if cursor in messages else None
            for message_id, message in (upsert or {}).items():
                if not isinstance(message, dict):
                    continue
                if message_id in messages and isinstance(messages[message_id], dict):
                    messages[message_id] = {**messages[message_id], **message}
                else:
                    messages[message_id] = message
            history["messages"] = messages
            chat["history"] = history
            return chat, True

        try:
            return self._write_locked_chat(
                id,
                apply,
                expected_revision=expected_revision,
                check_revision=True,
                wait_s=BROWSER_WRITE_WAIT_S,
            )
        except ChatWriteError:
            return None, "error"

    def get_recent_workspace_chat_refs(
        self,
        user_id: str,
        organization_id: str,
        *,
        days: int = 7,
        limit: int = 5,
        include_shared: bool = True,
    ) -> list[dict]:
        """Ids and revisions for the recent window, without the transcript JSON."""
        from sqlalchemy.orm import defer

        from open_webui.utils.chat_realtime import chat_revision

        cutoff = int(time.time()) - days * 24 * 60 * 60

        def listed(db):
            return db.query(Chat).options(defer(Chat.chat))

        with get_db() as db:
            own = (
                listed(db)
                .filter(
                    Chat.user_id == user_id,
                    Chat.organization_id == organization_id,
                    Chat.archived == False,  # noqa: E712
                    Chat.updated_at >= cutoff,
                )
                .order_by(Chat.updated_at.desc())
                .limit(limit)
                .all()
            )
            shared = []
            if include_shared:
                shared = (
                    listed(db)
                    .filter(
                        Chat.organization_id == organization_id,
                        Chat.visibility == "organization",
                        Chat.user_id != user_id,
                        Chat.archived == False,  # noqa: E712
                        Chat.updated_at >= cutoff,
                    )
                    .order_by(Chat.updated_at.desc())
                    .limit(limit)
                    .all()
                )
            seen = set()
            refs = []
            for chat in [*own, *shared]:
                if chat.id in seen:
                    continue
                seen.add(chat.id)
                refs.append(
                    {
                        "id": chat.id,
                        "updated_at": chat.updated_at,
                        "revision": chat_revision(chat),
                        "user_id": chat.user_id,
                        "organization_id": chat.organization_id,
                        "visibility": chat.visibility or "private",
                    }
                )
            return refs

    def insert_shared_chat_by_chat_id(self, chat_id: str) -> Optional[ChatModel]:
        with get_db() as db:
            # Get the existing chat to share
            chat = db.get(Chat, chat_id)
            if chat is None:
                return None
            # Check if the chat is already shared
            if chat.share_id:
                existing = db.get(Chat, chat.share_id)
                if existing:
                    return ChatModel.model_validate(existing)
            # Snapshot keeps the source organization so the row is valid, but stays
            # private so it does not appear in anyone's chat list.
            shared_chat = ChatModel(
                **{
                    "id": str(uuid.uuid4()),
                    "user_id": f"shared-{chat_id}",
                    "title": chat.title,
                    "chat": chat.chat,
                    "created_at": chat.created_at,
                    "updated_at": int(time.time()),
                    "organization_id": chat.organization_id,
                    "visibility": "private",
                }
            )
            shared_result = Chat(**shared_chat.model_dump())
            db.add(shared_result)
            db.commit()
            db.refresh(shared_result)

            # Update the original chat with the share_id
            result = (
                db.query(Chat)
                .filter_by(id=chat_id)
                .update({"share_id": shared_chat.id})
            )
            db.commit()
            return shared_chat if (shared_result and result) else None

    def update_shared_chat_by_chat_id(self, chat_id: str) -> Optional[ChatModel]:
        try:
            with get_db() as db:
                chat = db.get(Chat, chat_id)
                shared_chat = (
                    db.query(Chat).filter_by(user_id=f"shared-{chat_id}").first()
                )

                if shared_chat is None:
                    return self.insert_shared_chat_by_chat_id(chat_id)

                shared_chat.title = chat.title
                shared_chat.chat = chat.chat

                shared_chat.updated_at = int(time.time())
                db.commit()
                db.refresh(shared_chat)

                return ChatModel.model_validate(shared_chat)
        except Exception:
            return None

    def delete_shared_chat_by_chat_id(self, chat_id: str) -> bool:
        try:
            with get_db() as db:
                db.query(Chat).filter_by(user_id=f"shared-{chat_id}").delete()
                db.commit()

                return True
        except Exception:
            return False

    def update_chat_share_id_by_id(
        self, id: str, share_id: Optional[str]
    ) -> Optional[ChatModel]:
        try:
            with self._locked_chat(id) as (db, chat):
                chat.share_id = share_id
                db.commit()
                db.refresh(chat)
                return ChatModel.model_validate(chat)
        except Exception:
            return None

    def toggle_chat_pinned_by_id(self, id: str) -> Optional[ChatModel]:
        try:
            with self._locked_chat(id) as (db, chat):
                chat.pinned = not chat.pinned
                self._touch_visible(chat)
                db.commit()
                db.refresh(chat)
                result = ChatModel.model_validate(chat)
            self._schedule_visible_commit(id)
            return result
        except Exception:
            return None

    def toggle_chat_archive_by_id(self, id: str) -> Optional[ChatModel]:
        try:
            with self._locked_chat(id) as (db, chat):
                chat.archived = not chat.archived
                self._touch_visible(chat)
                db.commit()
                db.refresh(chat)
                result = ChatModel.model_validate(chat)
            self._schedule_visible_commit(id)
            return result
        except Exception:
            return None

    def archive_all_chats_by_user_id(self, user_id: str) -> bool:
        try:
            with get_db() as db:
                db.query(Chat).filter(_chat_visible_filter(user_id, user_id)).update(
                    {"archived": True}
                )
                db.commit()
                return True
        except Exception:
            return False

    def get_archived_chat_list_by_user_id(
        self, user_id: str, skip: int = 0, limit: int = 50
    ) -> list[ChatModel]:
        with get_db() as db:
            all_chats = (
                db.query(Chat)
                .filter(_chat_visible_filter(user_id, user_id))
                .filter_by(archived=True)
                .order_by(Chat.updated_at.desc())
                .all()
            )
            return [ChatModel.model_validate(chat) for chat in all_chats]

    def get_chat_list_by_user_id(
        self,
        user_id: str,
        include_archived: bool = False,
        skip: int = 0,
        limit: int = 50,
        organization_id: Optional[str] = None,
    ) -> list[ChatModel]:
        organization_id = organization_id or user_id
        with get_db() as db:
            query = db.query(Chat).filter(_chat_visible_filter(user_id, organization_id))
            if not include_archived:
                query = query.filter_by(archived=False)

            query = query.order_by(Chat.updated_at.desc())

            if skip:
                query = query.offset(skip)
            if limit:
                query = query.limit(limit)

            all_chats = query.all()
            return [ChatModel.model_validate(chat) for chat in all_chats]

    def get_chat_title_id_list_by_user_id(
        self,
        user_id: str,
        include_archived: bool = False,
        skip: Optional[int] = None,
        limit: Optional[int] = None,
        organization_id: Optional[str] = None,
    ) -> list[ChatTitleIdResponse]:
        from open_webui.utils.chat_timing import log_timing

        organization_id = organization_id or user_id
        t0 = time.perf_counter()
        with get_db() as db:
            query = (
                db.query(Chat)
                .filter(_chat_visible_filter(user_id, organization_id))
                .filter_by(folder_id=None)
            )
            query = query.filter(or_(Chat.pinned == False, Chat.pinned == None))

            if not include_archived:
                query = query.filter_by(archived=False)

            query = query.order_by(Chat.updated_at.desc()).with_entities(
                Chat.id,
                Chat.title,
                Chat.updated_at,
                Chat.created_at,
                Chat.organization_id,
                Chat.visibility,
                Chat.user_id,
            )

            if skip:
                query = query.offset(skip)
            if limit:
                query = query.limit(limit)

            all_chats = query.all()

            log_timing(
                "db.Chats.get_chat_title_id_list",
                time.perf_counter() - t0,
                n=len(all_chats),
                skip=skip,
                limit=limit,
            )

            # result has to be destrctured from sqlalchemy `row` and mapped to a dict since the `ChatModel`is not the returned dataclass.
            return [
                ChatTitleIdResponse.model_validate(
                    {
                        "id": chat[0],
                        "title": chat[1],
                        "updated_at": chat[2],
                        "created_at": chat[3],
                        "organization_id": chat[4],
                        "visibility": chat[5],
                        "user_id": chat[6],
                    }
                )
                for chat in all_chats
            ]

    def get_chat_title_id_list_by_organization_id(
        self,
        user_id: str,
        organization_id: str,
        include_archived: bool = False,
        skip: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> list[ChatTitleIdResponse]:
        return self.get_chat_title_id_list_by_user_id(
            user_id,
            include_archived=include_archived,
            skip=skip,
            limit=limit,
            organization_id=organization_id,
        )

    def count_chats_by_organization_id(
        self, organization_id: str, include_archived: bool = True
    ) -> int:
        with get_db() as db:
            query = db.query(Chat).filter_by(organization_id=organization_id)
            if not include_archived:
                query = query.filter_by(archived=False)
            return query.count()

    def update_chat_visibility(
        self, id: str, visibility: str
    ) -> Optional[ChatModel]:
        try:
            with self._locked_chat(id) as (db, chat):
                previous_visibility = chat.visibility
                chat.visibility = visibility
                # A private folder and a team folder are different lists. Leave
                # the chat unfiled so it shows up in the section it now belongs to.
                chat.folder_id = None
                self._touch_visible(chat)
                db.commit()
                db.refresh(chat)
                result = ChatModel.model_validate(chat)
            self._schedule_visible_commit(id, previous_visibility=previous_visibility)
            return result
        except Exception:
            return None

    def get_chat_list_by_chat_ids(
        self, chat_ids: list[str], skip: int = 0, limit: int = 50
    ) -> list[ChatModel]:
        with get_db() as db:
            all_chats = (
                db.query(Chat)
                .filter(Chat.id.in_(chat_ids))
                .filter_by(archived=False)
                .order_by(Chat.updated_at.desc())
                .all()
            )
            return [ChatModel.model_validate(chat) for chat in all_chats]

    def get_chat_by_id(self, id: str) -> Optional[ChatModel]:
        from open_webui.utils.chat_timing import log_timing

        t0 = time.perf_counter()
        try:
            with get_db() as db:
                chat = db.get(Chat, id)
                result = ChatModel.model_validate(chat)
            payload = result.chat if result else None
            log_timing(
                "db.Chats.get_chat_by_id",
                time.perf_counter() - t0,
                chat_id=id,
                chat_json_bytes=len(json.dumps(payload or {}, default=str)),
            )
            return result
        except Exception:
            return None

    def get_chat_by_share_id(self, id: str) -> Optional[ChatModel]:
        try:
            with get_db() as db:
                # it is possible that the shared link was deleted. hence,
                # we check if the chat is still shared by checking if a chat with the share_id exists
                chat = db.query(Chat).filter_by(share_id=id).first()

                if chat:
                    return self.get_chat_by_id(id)
                else:
                    return None
        except Exception:
            return None

    def get_chat_by_id_and_user_id(self, id: str, user_id: str) -> Optional[ChatModel]:
        try:
            with get_db() as db:
                chat = db.query(Chat).filter_by(id=id, user_id=user_id).first()
                return ChatModel.model_validate(chat)
        except Exception:
            return None

    def get_chats(self, skip: int = 0, limit: int = 50) -> list[ChatModel]:
        with get_db() as db:
            all_chats = (
                db.query(Chat)
                # .limit(limit).offset(skip)
                .order_by(Chat.updated_at.desc())
            )
            return [ChatModel.model_validate(chat) for chat in all_chats]

    def get_chats_by_user_id(self, user_id: str) -> list[ChatModel]:
        with get_db() as db:
            all_chats = (
                db.query(Chat)
                .filter_by(user_id=user_id)
                .order_by(Chat.updated_at.desc())
            )
            return [ChatModel.model_validate(chat) for chat in all_chats]

    def get_pinned_chats_by_user_id(
        self, user_id: str, organization_id: Optional[str] = None
    ) -> list[ChatModel]:
        organization_id = organization_id or user_id
        with get_db() as db:
            all_chats = (
                db.query(Chat)
                .filter(_chat_visible_filter(user_id, organization_id))
                .filter_by(pinned=True, archived=False)
                .order_by(Chat.updated_at.desc())
            )
            return [ChatModel.model_validate(chat) for chat in all_chats]

    def get_archived_chats_by_user_id(self, user_id: str) -> list[ChatModel]:
        with get_db() as db:
            all_chats = (
                db.query(Chat)
                .filter_by(user_id=user_id, archived=True)
                .order_by(Chat.updated_at.desc())
            )
            return [ChatModel.model_validate(chat) for chat in all_chats]

    def get_chats_by_user_id_and_search_text(
        self,
        user_id: str,
        search_text: str,
        include_archived: bool = False,
        skip: int = 0,
        limit: int = 60,
        organization_id: Optional[str] = None,
    ) -> list[ChatModel]:
        """
        Filters chats based on a search query using Python, allowing pagination using skip and limit.
        """
        search_text = search_text.lower().strip()
        organization_id = organization_id or user_id

        if not search_text:
            return self.get_chat_list_by_user_id(
                user_id, include_archived, skip, limit, organization_id=organization_id
            )

        search_text_words = search_text.split(" ")

        # search_text might contain 'tag:tag_name' format so we need to extract the tag_name, split the search_text and remove the tags
        tag_ids = [
            word.replace("tag:", "").replace(" ", "_").lower()
            for word in search_text_words
            if word.startswith("tag:")
        ]

        search_text_words = [
            word for word in search_text_words if not word.startswith("tag:")
        ]

        search_text = " ".join(search_text_words)

        with get_db() as db:
            query = db.query(Chat).filter(_chat_visible_filter(user_id, organization_id))

            if not include_archived:
                query = query.filter(Chat.archived == False)

            query = query.order_by(Chat.updated_at.desc())

            # Check if the database dialect is either 'sqlite' or 'postgresql'
            dialect_name = db.bind.dialect.name
            if dialect_name == "sqlite":
                # SQLite case: using JSON1 extension for JSON searching
                query = query.filter(
                    (
                        Chat.title.ilike(
                            f"%{search_text}%"
                        )  # Case-insensitive search in title
                        | text(
                            """
                            EXISTS (
                                SELECT 1 
                                FROM json_each(Chat.chat, '$.messages') AS message 
                                WHERE LOWER(message.value->>'content') LIKE '%' || :search_text || '%'
                            )
                            """
                        )
                    ).params(search_text=search_text)
                )

                # Check if there are any tags to filter, it should have all the tags
                if "none" in tag_ids:
                    query = query.filter(
                        text(
                            """
                            NOT EXISTS (
                                SELECT 1
                                FROM json_each(Chat.meta, '$.tags') AS tag
                            )
                            """
                        )
                    )
                elif tag_ids:
                    query = query.filter(
                        and_(
                            *[
                                text(
                                    f"""
                                    EXISTS (
                                        SELECT 1
                                        FROM json_each(Chat.meta, '$.tags') AS tag
                                        WHERE tag.value = :tag_id_{tag_idx}
                                    )
                                    """
                                ).params(**{f"tag_id_{tag_idx}": tag_id})
                                for tag_idx, tag_id in enumerate(tag_ids)
                            ]
                        )
                    )

            elif dialect_name == "postgresql":
                # PostgreSQL relies on proper JSON query for search
                query = query.filter(
                    (
                        Chat.title.ilike(
                            f"%{search_text}%"
                        )  # Case-insensitive search in title
                        | text(
                            """
                            EXISTS (
                                SELECT 1
                                FROM json_array_elements(Chat.chat->'messages') AS message
                                WHERE LOWER(message->>'content') LIKE '%' || :search_text || '%'
                            )
                            """
                        )
                    ).params(search_text=search_text)
                )

                # Check if there are any tags to filter, it should have all the tags
                if "none" in tag_ids:
                    query = query.filter(
                        text(
                            """
                            NOT EXISTS (
                                SELECT 1
                                FROM json_array_elements_text(Chat.meta->'tags') AS tag
                            )
                            """
                        )
                    )
                elif tag_ids:
                    query = query.filter(
                        and_(
                            *[
                                text(
                                    f"""
                                    EXISTS (
                                        SELECT 1
                                        FROM json_array_elements_text(Chat.meta->'tags') AS tag
                                        WHERE tag = :tag_id_{tag_idx}
                                    )
                                    """
                                ).params(**{f"tag_id_{tag_idx}": tag_id})
                                for tag_idx, tag_id in enumerate(tag_ids)
                            ]
                        )
                    )
            else:
                raise NotImplementedError(
                    f"Unsupported dialect: {db.bind.dialect.name}"
                )

            # Perform pagination at the SQL level
            all_chats = query.offset(skip).limit(limit).all()

            log.info(f"The number of chats: {len(all_chats)}")

            # Validate and return chats
            return [ChatModel.model_validate(chat) for chat in all_chats]

    def get_chats_by_folder_id_and_user_id(
        self, folder_id: str, user_id: str
    ) -> list[ChatModel]:
        return self.get_chats_in_folders([folder_id], user_id, "private")

    def get_chats_in_folders(
        self, folder_ids: list[str], user_id: str, visibility: str
    ) -> list[ChatModel]:
        if not folder_ids:
            return []
        with get_db() as db:
            query = db.query(Chat).filter(Chat.folder_id.in_(folder_ids))
            query = query.filter(or_(Chat.pinned == False, Chat.pinned == None))
            query = query.filter_by(archived=False)
            if visibility == "organization":
                query = query.filter(Chat.visibility == "organization")
            else:
                query = query.filter_by(user_id=user_id)
            query = query.order_by(Chat.updated_at.desc())
            return [ChatModel.model_validate(chat) for chat in query.all()]

    def clear_chat_folder_ids(self, folder_ids: list[str]) -> None:
        if not folder_ids:
            return
        with get_db() as db:
            db.query(Chat).filter(Chat.folder_id.in_(folder_ids)).update(
                {Chat.folder_id: None}, synchronize_session=False
            )
            db.commit()

    def get_chats_by_folder_ids_and_user_id(
        self, folder_ids: list[str], user_id: str
    ) -> list[ChatModel]:
        return self.get_chats_in_folders(folder_ids, user_id, "private")

    def update_chat_folder_id_by_id_and_user_id(
        self, id: str, user_id: str, folder_id: str
    ) -> Optional[ChatModel]:
        try:
            with self._locked_chat(id) as (db, chat):
                chat.folder_id = folder_id
                chat.pinned = False
                self._touch_visible(chat)
                db.commit()
                db.refresh(chat)
                result = ChatModel.model_validate(chat)
            self._schedule_visible_commit(id)
            return result
        except Exception:
            return None

    def get_chat_tags_by_id_and_user_id(self, id: str, user_id: str) -> list[TagModel]:
        with get_db() as db:
            chat = db.get(Chat, id)
            tags = chat.meta.get("tags", [])
            return [Tags.get_tag_by_name_and_user_id(tag, user_id) for tag in tags]

    def get_chat_list_by_user_id_and_tag_name(
        self, user_id: str, tag_name: str, skip: int = 0, limit: int = 50
    ) -> list[ChatModel]:
        with get_db() as db:
            query = db.query(Chat).filter_by(user_id=user_id)
            tag_id = tag_name.replace(" ", "_").lower()

            log.info(f"DB dialect name: {db.bind.dialect.name}")
            if db.bind.dialect.name == "sqlite":
                # SQLite JSON1 querying for tags within the meta JSON field
                query = query.filter(
                    text(
                        f"EXISTS (SELECT 1 FROM json_each(Chat.meta, '$.tags') WHERE json_each.value = :tag_id)"
                    )
                ).params(tag_id=tag_id)
            elif db.bind.dialect.name == "postgresql":
                # PostgreSQL JSON query for tags within the meta JSON field (for `json` type)
                query = query.filter(
                    text(
                        "EXISTS (SELECT 1 FROM json_array_elements_text(Chat.meta->'tags') elem WHERE elem = :tag_id)"
                    )
                ).params(tag_id=tag_id)
            else:
                raise NotImplementedError(
                    f"Unsupported dialect: {db.bind.dialect.name}"
                )

            all_chats = query.all()
            log.debug(f"all_chats: {all_chats}")
            return [ChatModel.model_validate(chat) for chat in all_chats]

    def add_chat_tag_by_id_and_user_id_and_tag_name(
        self, id: str, user_id: str, tag_name: str
    ) -> Optional[ChatModel]:
        tag = Tags.get_tag_by_name_and_user_id(tag_name, user_id)
        if tag is None:
            tag = Tags.insert_new_tag(tag_name, user_id)
        try:
            with self._locked_chat(id) as (db, chat):

                tag_id = tag.id
                if tag_id not in chat.meta.get("tags", []):
                    chat.meta = {
                        **chat.meta,
                        "tags": list(set(chat.meta.get("tags", []) + [tag_id])),
                    }

                db.commit()
                db.refresh(chat)
                return ChatModel.model_validate(chat)
        except Exception:
            return None

    def count_chats_by_tag_name_and_user_id(self, tag_name: str, user_id: str) -> int:
        with get_db() as db:  # Assuming `get_db()` returns a session object
            query = db.query(Chat).filter_by(user_id=user_id, archived=False)

            # Normalize the tag_name for consistency
            tag_id = tag_name.replace(" ", "_").lower()

            if db.bind.dialect.name == "sqlite":
                # SQLite JSON1 support for querying the tags inside the `meta` JSON field
                query = query.filter(
                    text(
                        f"EXISTS (SELECT 1 FROM json_each(Chat.meta, '$.tags') WHERE json_each.value = :tag_id)"
                    )
                ).params(tag_id=tag_id)

            elif db.bind.dialect.name == "postgresql":
                # PostgreSQL JSONB support for querying the tags inside the `meta` JSON field
                query = query.filter(
                    text(
                        "EXISTS (SELECT 1 FROM json_array_elements_text(Chat.meta->'tags') elem WHERE elem = :tag_id)"
                    )
                ).params(tag_id=tag_id)

            else:
                raise NotImplementedError(
                    f"Unsupported dialect: {db.bind.dialect.name}"
                )

            # Get the count of matching records
            count = query.count()

            # Debugging output for inspection
            log.info(f"Count of chats for tag '{tag_name}': {count}")

            return count

    def delete_tag_by_id_and_user_id_and_tag_name(
        self, id: str, user_id: str, tag_name: str
    ) -> bool:
        try:
            with self._locked_chat(id) as (db, chat):
                tags = chat.meta.get("tags", [])
                tag_id = tag_name.replace(" ", "_").lower()

                tags = [tag for tag in tags if tag != tag_id]
                chat.meta = {
                    **chat.meta,
                    "tags": list(set(tags)),
                }
                db.commit()
                return True
        except Exception:
            return False

    def delete_all_tags_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        try:
            with self._locked_chat(id) as (db, chat):
                chat.meta = {
                    **chat.meta,
                    "tags": [],
                }
                db.commit()

                return True
        except Exception:
            return False

    def delete_chat_by_id(self, id: str) -> bool:
        try:
            with get_db() as db:
                db.query(Chat).filter_by(id=id).delete()
                db.commit()

                return True and self.delete_shared_chat_by_chat_id(id)
        except Exception:
            return False

    def delete_chat_by_id_and_user_id(self, id: str, user_id: str) -> bool:
        try:
            with get_db() as db:
                db.query(Chat).filter_by(id=id, user_id=user_id).delete()
                db.commit()

                return True and self.delete_shared_chat_by_chat_id(id)
        except Exception:
            return False

    def delete_chats_by_user_id(self, user_id: str) -> bool:
        try:
            with get_db() as db:
                self.delete_shared_chats_by_user_id(user_id)
                db.query(Chat).filter_by(
                    user_id=user_id, organization_id=user_id
                ).delete()
                db.query(Chat).filter_by(user_id=user_id, visibility="private").delete()
                db.commit()
                return True
        except Exception:
            return False

    def delete_chats_by_user_id_and_folder_id(
        self, user_id: str, folder_id: str
    ) -> bool:
        try:
            with get_db() as db:
                db.query(Chat).filter_by(user_id=user_id, folder_id=folder_id).delete()
                db.commit()

                return True
        except Exception:
            return False

    def delete_shared_chats_by_user_id(self, user_id: str) -> bool:
        try:
            with get_db() as db:
                chats_by_user = db.query(Chat).filter_by(user_id=user_id).all()
                shared_chat_ids = [f"shared-{chat.id}" for chat in chats_by_user]

                db.query(Chat).filter(Chat.user_id.in_(shared_chat_ids)).delete()
                db.commit()

                return True
        except Exception:
            return False


Chats = ChatTable()
