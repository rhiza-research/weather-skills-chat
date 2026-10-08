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
        self.Chats.append_message_statuses(
            self.chat.id, "a1", [{"description": "Searching..."}]
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
