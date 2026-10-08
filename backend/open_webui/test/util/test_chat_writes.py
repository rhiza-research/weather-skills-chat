import unittest

from test.util.abstract_integration_test import AbstractPostgresTest
from test.util.mock_user import mock_webui_user


def _history(*messages, current):
    bag = {message["id"]: message for message in messages}
    return {"currentId": current, "messages": bag}


def _msg(id, role, parent, children, content="hi"):
    return {
        "id": id,
        "role": role,
        "parentId": parent,
        "childrenIds": children,
        "content": content,
    }


class TestChatWrites(AbstractPostgresTest):
    BASE_PATH = "/api/v1/chats"

    def setup_method(self):
        super().setup_method()
        from open_webui.models.chats import ChatForm, Chats

        self.chats = Chats
        created = self.chats.insert_new_chat(
            "2",
            ChatForm(
                chat={
                    "title": "writes",
                    "history": _history(
                        _msg("u1", "user", None, ["a1"]),
                        _msg("a1", "assistant", "u1", []),
                        current="a1",
                    ),
                }
            ),
        )
        self.chat_id = created.id
        self.revision = created.meta.get("revision") or 1

    def test_history_delete_rewires_parent_and_current(self):
        updated, state = self.chats.apply_history_patch(
            self.chat_id,
            upsert={
                "u1": {**_msg("u1", "user", None, []), "childrenIds": []},
            },
            delete_ids=["a1"],
            expected_revision=self.revision,
        )
        assert state == "ok"
        history = updated.chat["history"]
        assert "a1" not in history["messages"]
        assert history["messages"]["u1"]["childrenIds"] == []
        assert history["currentId"] == "u1"

    def test_append_turn_unknown_parent_conflicts(self):
        stored, state = self.chats.append_turn(
            self.chat_id,
            {
                "id": "u-orphan",
                "parentId": "missing",
                "childrenIds": ["a-orphan"],
                "role": "user",
                "content": "hi",
            },
            {
                "id": "a-orphan",
                "parentId": "u-orphan",
                "childrenIds": [],
                "role": "assistant",
                "content": "",
            },
            self.revision,
        )
        assert state == "conflict"
        assert "u-orphan" not in stored.chat["history"]["messages"]

    def test_stale_revision_conflicts_without_writing(self):
        stored, state = self.chats.append_turn(
            self.chat_id,
            {
                "id": "u2",
                "parentId": "a1",
                "childrenIds": ["a2"],
                "role": "user",
                "content": "next",
            },
            {
                "id": "a2",
                "parentId": "u2",
                "childrenIds": [],
                "role": "assistant",
                "content": "",
            },
            self.revision - 1 if self.revision else 0,
        )
        assert state == "conflict"
        assert "u2" not in stored.chat["history"]["messages"]

    def test_status_then_content_keeps_both(self):
        self.chats.append_message_statuses(
            self.chat_id, "a1", [{"description": "Searching…"}]
        )
        self.chats.upsert_message_to_chat_by_id_and_message_id(
            self.chat_id,
            "a1",
            {"content": "done", "done": True},
            bump_revision=False,
        )
        chat = self.chats.get_chat_by_id(self.chat_id)
        message = chat.chat["history"]["messages"]["a1"]
        assert message["content"] == "done"
        assert message["statusHistory"][0]["description"] == "Searching…"

    def test_history_conflict_message_is_readable(self):
        with mock_webui_user(id="2"):
            response = self.fast_api_client.post(
                self.create_url(f"/{self.chat_id}/history"),
                json={"upsert": {"a1": {"content": "x"}}, "expected_revision": 0},
            )
        assert response.status_code == 409
        body = response.json()
        detail = body.get("detail")
        message = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        assert "409" not in message
        assert "another user" in message.lower()

    def test_without_transcript_omits_messages(self):
        skinny = self.chats.get_chat_without_transcript(self.chat_id)
        self.assertEqual(skinny.id, self.chat_id)
        self.assertEqual(skinny.chat, {})
        full = self.chats.get_chat_by_id(self.chat_id)
        self.assertIn("a1", full.chat["history"]["messages"])
