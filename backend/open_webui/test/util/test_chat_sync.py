"""Failing-first coverage for chat write, history, and watch bugs."""

import asyncio
import inspect
import time

from test.util.abstract_integration_test import AbstractPostgresTest


def _tree():
    return {
        "title": "tree",
        "history": {
            "currentId": "a1",
            "messages": {
                "u1": {
                    "id": "u1",
                    "parentId": None,
                    "childrenIds": ["a1"],
                    "role": "user",
                    "content": "hi",
                },
                "a1": {
                    "id": "a1",
                    "parentId": "u1",
                    "childrenIds": [],
                    "role": "assistant",
                    "content": "yo",
                    "done": True,
                },
            },
        },
    }


class TestChatSyncWrites(AbstractPostgresTest):
    def setup_method(self):
        super().setup_method()
        from open_webui.models.chats import ChatForm, Chats

        self.Chats = Chats
        self.chat = Chats.insert_new_chat("2", ChatForm(chat=_tree()))

    def _revision(self, chat=None):
        from open_webui.utils.chat_realtime import chat_revision

        return chat_revision(chat or self.chat)

    def test_unused_full_workspace_loader_is_gone(self):
        assert not hasattr(self.Chats, "get_recent_workspace_chats")

    def test_delete_cleans_parent_children_and_points_current_at_parent(self):
        updated, state = self.Chats.apply_history_patch(self.chat.id, {}, ["a1"], None)
        assert state == "ok"
        history = updated.chat["history"]
        assert "a1" not in history["messages"]
        assert history["messages"]["u1"]["childrenIds"] == []
        assert history["currentId"] == "u1"

    def test_deleting_a_user_message_and_its_reply_points_current_at_the_survivor(self):
        from open_webui.models.chats import ChatForm

        tree = _tree()
        tree["history"]["currentId"] = "a2"
        tree["history"]["messages"]["a1"]["childrenIds"] = ["u2"]
        tree["history"]["messages"]["u2"] = {
            "id": "u2",
            "parentId": "a1",
            "childrenIds": ["a2"],
            "role": "user",
            "content": "again",
        }
        tree["history"]["messages"]["a2"] = {
            "id": "a2",
            "parentId": "u2",
            "childrenIds": [],
            "role": "assistant",
            "content": "reply",
            "done": True,
        }
        chat = self.Chats.insert_new_chat("2", ChatForm(chat=tree))
        # Messages.svelte deletes the user message together with its replies.
        updated, state = self.Chats.apply_history_patch(chat.id, {}, ["u2", "a2"], None)
        assert state == "ok"
        history = updated.chat["history"]
        assert history["currentId"] == "a1"
        assert history["messages"]["a1"]["childrenIds"] == []

    def test_revision_is_read_without_the_transcript(self):
        assert self.Chats.get_chat_revision(self.chat.id) == self._revision()
        self.Chats.apply_history_patch(self.chat.id, {"a1": {"content": "x"}}, [], None)
        assert self.Chats.get_chat_revision(self.chat.id) == self._revision() + 1
        assert self.Chats.get_chat_revision("missing-chat") == 0

    def test_append_turn_rejects_an_unknown_parent(self):
        updated, state = self.Chats.append_turn(
            self.chat.id,
            {
                "id": "u-orphan",
                "parentId": "missing-parent",
                "childrenIds": ["a-orphan"],
                "role": "user",
                "content": "orphan",
            },
            {
                "id": "a-orphan",
                "parentId": "u-orphan",
                "childrenIds": [],
                "role": "assistant",
                "content": "",
            },
            self._revision(),
        )
        assert state != "ok"
        stored = self.Chats.get_chat_by_id(self.chat.id)
        assert "u-orphan" not in (stored.chat.get("history") or {}).get("messages", {})

    def test_unexpected_history_write_error_is_not_called_missing(self, monkeypatch):
        class Boom:
            def __enter__(self):
                raise RuntimeError("disk full")

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("open_webui.models.chats.get_db", lambda: Boom())
        updated, state = self.Chats.apply_history_patch(self.chat.id, {}, ["a1"], None)
        assert updated is None
        assert state == "error"

    def test_update_chat_by_id_does_not_swallow_errors(self, monkeypatch):
        from open_webui.models.chats import ChatWriteError

        def boom(*_args, **_kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr("open_webui.models.chats.get_db", boom)
        try:
            self.Chats.update_chat_by_id(self.chat.id, self.chat.chat)
        except ChatWriteError:
            return
        except RuntimeError:
            return
        raise AssertionError("update_chat_by_id swallowed the database error")

    def test_status_flush_merges_onto_later_content(self, monkeypatch):
        stale = self.Chats.get_chat_by_id(self.chat.id)
        self.Chats.upsert_message_to_chat_by_id_and_message_id(
            self.chat.id, "a1", {"content": "hello from stream"}, bump_revision=False
        )
        original_get = self.Chats.get_chat_by_id

        def stale_then_real(chat_id):
            if not getattr(stale_then_real, "used", False):
                stale_then_real.used = True
                return stale
            return original_get(chat_id)

        monkeypatch.setattr(self.Chats, "get_chat_by_id", stale_then_real)
        self.Chats.merge_message_updates(
            self.chat.id, "a1", {"status": {"description": "Searching..."}}
        )
        latest = original_get(self.chat.id)
        message = latest.chat["history"]["messages"]["a1"]
        assert message["content"] == "hello from stream"
        assert any(
            item.get("description") == "Searching..."
            for item in (message.get("statusHistory") or [])
        )

    def test_second_writer_with_the_same_revision_conflicts(self):
        revision = self._revision()
        first, first_state = self.Chats.append_turn(
            self.chat.id,
            {
                "id": "u2",
                "parentId": "a1",
                "childrenIds": ["a2"],
                "role": "user",
                "content": "first",
            },
            {
                "id": "a2",
                "parentId": "u2",
                "childrenIds": [],
                "role": "assistant",
                "content": "",
            },
            revision,
        )
        assert first_state == "ok"
        second, second_state = self.Chats.append_turn(
            self.chat.id,
            {
                "id": "u3",
                "parentId": "a1",
                "childrenIds": ["a3"],
                "role": "user",
                "content": "second",
            },
            {
                "id": "a3",
                "parentId": "u3",
                "childrenIds": [],
                "role": "assistant",
                "content": "",
            },
            revision,
        )
        assert second_state == "conflict"
        assert "u3" not in (second.chat.get("history") or {}).get("messages", {})
        stored = self.Chats.get_chat_by_id(self.chat.id)
        assert stored.chat["history"]["messages"]["u2"]["content"] == "first"

    def test_access_row_does_not_load_the_transcript(self):
        row = self.Chats.get_chat_access_row(self.chat.id)
        assert row.id == self.chat.id
        assert row.user_id == "2"
        assert row.visibility == "private"
        assert getattr(row, "chat", None) in (None, {})

    def test_chat_watch_uses_the_skinny_access_row(self):
        from open_webui.utils import chat_realtime

        source = inspect.getsource(chat_realtime)
        assert "get_chat_access_row" in source


class TestChatRealtimeSync(AbstractPostgresTest):
    def setup_method(self):
        super().setup_method()
        from open_webui.models.chats import ChatForm, Chats
        from open_webui.models.users import Users

        self.Chats = Chats
        Users.insert_new_user(
            id="owner",
            name="owner",
            email="owner@example.com",
            profile_image_url="/o.png",
            role="user",
        )
        Users.insert_new_user(
            id="member",
            name="member",
            email="member@example.com",
            profile_image_url="/m.png",
            role="user",
        )
        self.chat = Chats.insert_new_chat("owner", ChatForm(chat=_tree()))

    def test_making_a_team_chat_private_emits_removed_to_members(self):
        from open_webui.internal.db import get_db
        from open_webui.models.chats import Chat
        from open_webui.models.organizations import OrganizationForm, Organizations
        from open_webui.socket.main import USER_POOL
        from open_webui.utils.chat_realtime import emit_chat_list

        created = Organizations.insert_new_organization(
            "owner", OrganizationForm(name=f"Team {time.time()}")
        )
        Organizations.add_member(created.id, "member", "user")
        with get_db() as db:
            item = db.get(Chat, self.chat.id)
            item.organization_id = created.id
            item.visibility = "private"
            db.commit()
        private = self.Chats.get_chat_by_id(self.chat.id)

        events = []

        class FakeSio:
            async def emit(self, event, payload=None, to=None):
                events.append({"event": event, "payload": payload, "to": to})

        from open_webui.utils import chat_realtime

        chat_realtime.sio = FakeSio()
        USER_POOL["member"] = ["sid-member"]
        USER_POOL["owner"] = ["sid-owner"]

        asyncio.run(emit_chat_list(private, previous_visibility="organization"))
        member_rows = [
            item
            for item in events
            if item["to"] == "sid-member" and item["event"] == "chat:list"
        ]
        assert member_rows
        assert member_rows[0]["payload"].get("removed") is True

    def test_deleting_one_chat_keeps_other_watches_for_the_session(self):
        from open_webui.models.chats import ChatForm
        from open_webui.utils.chat_realtime import (
            WATCHES,
            publish_chat_removed,
            set_watch,
        )

        other = self.Chats.insert_new_chat("owner", ChatForm(chat=_tree()))
        set_watch("sid-1", "owner", [self.chat.id, other.id], self.chat.id)
        asyncio.run(publish_chat_removed(self.chat))
        remaining = WATCHES.get("sid-1") or {}
        assert other.id in (remaining.get("ids") or [])

    def test_schedule_artifacts_reruns_when_a_write_lands_during_listing(self, monkeypatch):
        from open_webui.utils import chat_realtime

        calls = {"n": 0}

        def fake_list(_chat_id):
            calls["n"] += 1
            time.sleep(0.05)
            return [{"name": f"file-{calls['n']}.txt"}]

        async def fake_emit(_chat_id, files):
            calls.setdefault("files", []).append(list(files))

        monkeypatch.setattr(chat_realtime, "ARTIFACT_DEBOUNCE_SECONDS", 0.01)
        monkeypatch.setattr("open_webui.utils.artifacts.list_artifacts", fake_list)
        monkeypatch.setattr(chat_realtime, "emit_chat_artifacts", fake_emit)
        chat_realtime._artifact_tasks.clear()

        async def run():
            chat_realtime.schedule_artifacts(self.chat.id)
            await asyncio.sleep(0.03)
            chat_realtime.schedule_artifacts(self.chat.id)
            await asyncio.sleep(0.3)

        asyncio.run(run())
        assert calls["n"] >= 2

    def test_headless_completion_does_not_bump_revision(self):
        from open_webui.socket.main import get_event_emitter
        from open_webui.utils.chat_realtime import chat_revision

        before = chat_revision(self.Chats.get_chat_by_id(self.chat.id))
        emitter = get_event_emitter(
            {
                "user_id": "owner",
                "chat_id": self.chat.id,
                "message_id": "a1",
                "headless": True,
            },
            update_db=True,
        )
        asyncio.run(
            emitter(
                {
                    "type": "chat:completion",
                    "data": {"done": True, "content": "automation done"},
                }
            )
        )
        after = self.Chats.get_chat_by_id(self.chat.id)
        assert chat_revision(after) == before
        assert after.chat["history"]["messages"]["a1"]["done"] is True
        assert after.chat["history"]["messages"]["a1"]["content"] == "automation done"

    def test_execute_events_go_only_to_the_originating_session(self, monkeypatch):
        from open_webui.socket import main as socket_main
        from open_webui.socket.main import USER_POOL, get_event_emitter
        from open_webui.utils.chat_realtime import WATCH_INDEX, set_watch

        events = []

        class FakeSio:
            async def emit(self, event, payload=None, to=None):
                events.append({"event": event, "payload": payload, "to": to})

        monkeypatch.setattr(socket_main, "sio", FakeSio())
        USER_POOL["owner"] = ["sid-owner"]
        set_watch("sid-watcher", "member", [self.chat.id], self.chat.id)
        WATCH_INDEX[self.chat.id] = ["sid-watcher"]
        emitter = get_event_emitter(
            {
                "user_id": "owner",
                "chat_id": self.chat.id,
                "message_id": "a1",
                "session_id": "sid-origin",
            },
            update_db=False,
        )
        asyncio.run(emitter({"type": "execute", "data": {"code": "1"}}))
        targets = [item["to"] for item in events if item["event"] == "chat-events"]
        assert targets == ["sid-origin"]


class TestChatWatchLimit(AbstractPostgresTest):
    def test_watch_checks_at_most_the_cap_and_keeps_the_active_chat(self, monkeypatch):
        from types import SimpleNamespace

        from open_webui.socket.main import sio
        from open_webui.utils import chat_realtime

        user = SimpleNamespace(id="owner", role="user")
        checked = []

        def access_row(chat_id):
            checked.append(chat_id)
            return SimpleNamespace(
                id=chat_id,
                user_id="owner",
                organization_id="owner",
                visibility="private",
            )

        monkeypatch.setattr(chat_realtime, "_user_for_sid", lambda _sid: user)
        monkeypatch.setattr(chat_realtime.Chats, "get_chat_access_row", access_row)
        handler = sio.handlers["/"]["chat:watch"]

        requested = [f"chat-{index}" for index in range(100)]
        requested += requested[:10]  # duplicates are checked once
        active = "chat-99"
        result = asyncio.run(handler("sid-cap", {"ids": requested, "active": active}))

        assert len(checked) == chat_realtime.MAX_WATCHED_CHATS
        assert len(set(checked)) == len(checked)
        assert checked[0] == active
        assert result["active"] == active
        assert len(result["ids"]) == chat_realtime.MAX_WATCHED_CHATS
        chat_realtime.clear_watch("sid-cap")


class TestEmitterAndRecheck(AbstractPostgresTest):
    def setup_method(self):
        super().setup_method()
        from open_webui.models.chats import ChatForm, Chats
        from open_webui.models.users import Users
        from open_webui.utils import chat_realtime

        # Watches are process-wide. Start from none so a full recheck only
        # sees this test's sessions.
        for index in (
            chat_realtime.WATCHES,
            chat_realtime.WATCH_INDEX,
            chat_realtime.ACTIVE_INDEX,
        ):
            index.clear()

        self.Chats = Chats
        for user_id in ("owner", "member"):
            Users.insert_new_user(
                id=user_id,
                name=user_id,
                email=f"{user_id}@example.com",
                profile_image_url="/p.png",
                role="user",
            )
        self.chat = Chats.insert_new_chat("owner", ChatForm(chat=_tree()))

    def _fake_sio(self, monkeypatch, *modules):
        events = []

        class FakeSio:
            async def emit(self, event, payload=None, to=None):
                events.append({"event": event, "payload": payload, "to": to})

        fake = FakeSio()
        for module in modules:
            monkeypatch.setattr(module, "sio", fake)
        return events

    def test_stream_events_reach_owner_and_watchers_without_access_queries(
        self, monkeypatch
    ):
        from open_webui.socket import main as socket_main
        from open_webui.socket.main import USER_POOL, get_event_emitter
        from open_webui.utils.chat_realtime import clear_watch, set_watch

        events = self._fake_sio(monkeypatch, socket_main)

        def no_queries(*_args, **_kwargs):
            raise AssertionError("an emit must not query chat access")

        monkeypatch.setattr(self.Chats, "get_chat_access_row", no_queries)
        monkeypatch.setattr(self.Chats, "get_chat_by_id", no_queries)
        USER_POOL["owner"] = ["sid-owner"]
        set_watch("sid-member", "member", [self.chat.id], self.chat.id)
        try:
            emitter = get_event_emitter(
                {"user_id": "owner", "chat_id": self.chat.id, "message_id": "a1"},
                update_db=False,
            )
            asyncio.run(
                emitter({"type": "chat:message:delta", "data": {"content": "x"}})
            )
        finally:
            clear_watch("sid-member")
            USER_POOL.pop("owner", None)
        targets = sorted(e["to"] for e in events if e["event"] == "chat-events")
        assert targets == ["sid-member", "sid-owner"]

    def test_removing_a_member_evicts_their_watch_on_a_team_chat(self, monkeypatch):
        from open_webui.internal.db import get_db
        from open_webui.models.chats import Chat
        from open_webui.models.organizations import OrganizationForm, Organizations
        from open_webui.utils import chat_realtime

        org = Organizations.insert_new_organization(
            "owner", OrganizationForm(name=f"Team {time.time()}")
        )
        Organizations.add_member(org.id, "member", "user")
        with get_db() as db:
            item = db.get(Chat, self.chat.id)
            item.organization_id = org.id
            item.visibility = "organization"
            db.commit()
        events = self._fake_sio(monkeypatch, chat_realtime)
        chat_realtime.set_watch("sid-member", "member", [self.chat.id], self.chat.id)
        chat_realtime.set_watch("sid-owner", "owner", [self.chat.id], self.chat.id)
        try:
            asyncio.run(chat_realtime.recheck_watches("member"))
            assert sorted(chat_realtime.watcher_session_ids(self.chat.id)) == [
                "sid-member",
                "sid-owner",
            ]
            assert events == []

            Organizations.remove_member(org.id, "member")
            asyncio.run(chat_realtime.recheck_watches("member"))
            assert chat_realtime.watcher_session_ids(self.chat.id) == ["sid-owner"]
            assert events == [
                {
                    "event": "chat:evict",
                    "payload": {"id": self.chat.id},
                    "to": "sid-member",
                }
            ]
        finally:
            chat_realtime.clear_watch("sid-member")
            chat_realtime.clear_watch("sid-owner")

    def test_recheck_without_a_user_evicts_watches_on_deleted_chats(self, monkeypatch):
        from open_webui.utils import chat_realtime

        events = self._fake_sio(monkeypatch, chat_realtime)
        chat_realtime.set_watch("sid-owner", "owner", [self.chat.id], None)
        try:
            self.Chats.delete_chat_by_id(self.chat.id)
            asyncio.run(chat_realtime.recheck_watches())
            assert chat_realtime.watcher_session_ids(self.chat.id) == []
            assert [e["to"] for e in events] == ["sid-owner"]
        finally:
            chat_realtime.clear_watch("sid-owner")


class TestStreamedPartsAreSaved(AbstractPostgresTest):
    def test_the_emitter_saves_usage_sources_runs_files_and_the_latest_status(self):
        from open_webui.models.chats import ChatForm, Chats
        from open_webui.socket.main import get_event_emitter
        from open_webui.utils.chat_realtime import flush_message_updates_now

        chat = Chats.insert_new_chat("2", ChatForm(chat=_tree()))
        emit = get_event_emitter(
            {"user_id": "2", "chat_id": chat.id, "message_id": "a1"}, update_db=True
        )
        image = {"type": "image", "url": "/cache/image/1.png"}

        async def stream():
            await emit(
                {
                    "type": "status",
                    "data": {
                        "action": "web_search",
                        "description": "Searched 2 sites",
                        "done": True,
                    },
                }
            )
            await emit(
                {
                    "type": "status",
                    "data": {
                        "action": "waiting_response",
                        "description": "Waiting for model…",
                        "done": False,
                    },
                }
            )
            for second in (1, 2, 3):
                await emit(
                    {
                        "type": "status",
                        "data": {
                            "action": "waiting_response",
                            "description": f"Still waiting for model… ({second}s)",
                            "done": False,
                        },
                    }
                )
            await emit(
                {
                    "type": "status",
                    "data": {"action": "generation_heartbeat", "done": False},
                }
            )
            await emit(
                {
                    "type": "chat:completion",
                    "data": {"usage": {"prompt_tokens": 10, "cost": 0.5}},
                }
            )
            await emit(
                {
                    "type": "chat:completion",
                    "data": {"usage": {"prompt_tokens": 5, "cost": 0.25}},
                }
            )
            await emit({"type": "citation", "data": {"source": {"name": "doc"}}})
            await emit(
                {
                    "type": "source",
                    "data": {"type": "code_execution", "id": "run-1", "result": None},
                }
            )
            await emit(
                {
                    "type": "source",
                    "data": {
                        "type": "code_execution",
                        "id": "run-1",
                        "result": {"output": "4"},
                    },
                }
            )
            await emit({"type": "files", "data": {"files": [image]}})
            await emit({"type": "files", "data": {"files": [image]}})
            await emit(
                {
                    "type": "status",
                    "data": {
                        "action": "waiting_response",
                        "description": "Waiting for model…",
                        "done": True,
                        "hidden": True,
                    },
                }
            )
            flush_message_updates_now(chat.id, "a1")

        asyncio.run(stream())
        message = Chats.get_chat_by_id(chat.id).chat["history"]["messages"]["a1"]
        assert message["content"] == "yo"
        assert message["statusHistory"] == [
            {
                "action": "waiting_response",
                "description": "Waiting for model…",
                "done": True,
                "hidden": True,
            }
        ]
        assert message["usage"] == {"prompt_tokens": 15, "cost": 0.75}
        assert message["sources"] == [{"source": {"name": "doc"}}]
        assert message["code_executions"] == [
            {"type": "code_execution", "id": "run-1", "result": {"output": "4"}}
        ]
        assert message["files"] == [image]

    def test_waiting_ticks_alone_write_nothing(self):
        from open_webui.models.chats import ChatForm, Chats
        from open_webui.socket.main import get_event_emitter
        from open_webui.utils import chat_realtime

        chat = Chats.insert_new_chat("2", ChatForm(chat=_tree()))
        emit = get_event_emitter(
            {"user_id": "2", "chat_id": chat.id, "message_id": "a1"}, update_db=True
        )

        async def stream():
            for second in range(5):
                await emit(
                    {
                        "type": "status",
                        "data": {
                            "action": "waiting_response",
                            "description": f"({second}s)",
                            "done": False,
                        },
                    }
                )
            await emit(
                {
                    "type": "status",
                    "data": {"action": "generation_heartbeat", "done": False},
                }
            )

        asyncio.run(stream())
        assert (chat.id, "a1") not in chat_realtime._pending_updates


class TestChatWriteLocking(AbstractPostgresTest):
    def setup_method(self):
        super().setup_method()
        from open_webui.models.chats import ChatForm, Chats

        self.Chats = Chats
        self.chat = Chats.insert_new_chat("2", ChatForm(chat=_tree()))

    def _message(self):
        return self.Chats.get_chat_by_id(self.chat.id).chat["history"]["messages"]["a1"]

    def test_concurrent_writes_from_threads_all_survive_on_sqlite(self):
        from concurrent.futures import ThreadPoolExecutor

        def add_one(_):
            self.Chats.merge_message_updates(
                self.chat.id, "a1", {"usage": {"total_tokens": 1}}
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add_one, range(20)))
        assert self._message()["usage"] == {"total_tokens": 20}

    def test_a_title_change_keeps_a_reply_saved_just_before(self):
        self.Chats.upsert_message_to_chat_by_id_and_message_id(
            self.chat.id,
            "a1",
            {"content": "the full reply", "done": True},
            bump_revision=False,
        )
        self.Chats.update_chat_title_by_id(self.chat.id, "Renamed")
        stored = self.Chats.get_chat_by_id(self.chat.id)
        assert stored.title == "Renamed"
        assert stored.chat["history"]["messages"]["a1"]["content"] == "the full reply"

    def test_appended_text_lands_at_the_end(self):
        self.Chats.append_message_content(self.chat.id, "a1", " and more")
        assert self._message()["content"] == "yo and more"

    def test_postgres_relies_on_the_row_lock_not_a_process_lock(self, monkeypatch):
        from contextlib import contextmanager
        from types import SimpleNamespace

        from open_webui.models import chats as chats_module

        session = SimpleNamespace(
            bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        )

        @contextmanager
        def fake_db():
            yield session

        def no_process_lock(_chat_id):
            raise AssertionError("Postgres writes must not take a process lock")

        monkeypatch.setattr(chats_module, "get_db", fake_db)
        monkeypatch.setattr(chats_module, "_chat_write_lock", no_process_lock)
        monkeypatch.setattr(
            self.Chats, "_lock_chat_row", lambda db, chat_id, wait_s: "row"
        )
        with self.Chats._locked_chat(self.chat.id) as (db, row):
            assert db is session
            assert row == "row"


class TestFinalReplySave(AbstractPostgresTest):
    def setup_method(self):
        super().setup_method()
        from open_webui.models.chats import ChatForm, Chats
        from open_webui.utils import chat_realtime

        self.Chats = Chats
        self.realtime = chat_realtime
        self.chat = Chats.insert_new_chat("2", ChatForm(chat=_tree()))

    def test_the_message_the_user_sees(self):
        assert self.realtime.REPLY_SAVE_FAILED_MESSAGE == (
            "There was an error saving the response from the server. Please retry"
        )

    def test_a_save_that_fails_twice_then_works_keeps_text_and_streamed_parts(
        self, monkeypatch
    ):
        from open_webui.models.chats import ChatWriteError

        monkeypatch.setattr(self.realtime, "FINAL_SAVE_RETRY_SECONDS", (0.01, 0.01))
        real_save = self.Chats.save_reply
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ChatWriteError("busy", busy=True)
            return real_save(*args, **kwargs)

        monkeypatch.setattr(self.Chats, "save_reply", flaky)

        async def run():
            self.realtime.schedule_message_update(
                self.chat.id, "a1", "usage", {"total_tokens": 7}
            )
            return await self.realtime.save_final_reply(
                self.chat.id, "a1", {"content": "final answer", "done": True}
            )

        assert asyncio.run(run()) is True
        assert calls["n"] == 3
        message = self.Chats.get_chat_by_id(self.chat.id).chat["history"]["messages"][
            "a1"
        ]
        assert message["content"] == "final answer"
        assert message["usage"] == {"total_tokens": 7}

    def test_a_save_that_keeps_failing_reports_false_instead_of_raising(
        self, monkeypatch
    ):
        monkeypatch.setattr(self.realtime, "FINAL_SAVE_RETRY_SECONDS", (0.01, 0.01))
        calls = {"n": 0}

        def broken(*_args, **_kwargs):
            calls["n"] += 1
            raise RuntimeError("database unreachable")

        monkeypatch.setattr(self.Chats, "save_reply", broken)
        saved = asyncio.run(
            self.realtime.save_final_reply(
                self.chat.id, "a1", {"content": "x", "done": True}
            )
        )
        assert saved is False
        assert calls["n"] == 3
