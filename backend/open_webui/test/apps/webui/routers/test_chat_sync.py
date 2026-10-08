"""HTTP coverage for chat conflict, turn, and delete-order bugs."""

from test.util.abstract_integration_test import AbstractPostgresTest
from test.util.mock_user import mock_webui_user


def _tree():
    return {
        "title": "sync",
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


class TestChatSyncRoutes(AbstractPostgresTest):
    BASE_PATH = "/api/v1/chats"

    def setup_method(self):
        super().setup_method()
        from open_webui.models.chats import ChatForm, Chats

        self.chats = Chats
        self.chat = Chats.insert_new_chat("2", ChatForm(chat=_tree()))

    def test_history_conflict_has_revision_and_user_copy(self):
        with mock_webui_user(id="2"):
            response = self.fast_api_client.post(
                self.create_url(f"/{self.chat.id}/history"),
                json={
                    "upsert": {"a1": {"content": "edited"}},
                    "expected_revision": 0,
                },
            )
        # Seeded chats start at revision 0; bump once so 0 is stale.
        if response.status_code != 409:
            with mock_webui_user(id="2"):
                self.fast_api_client.post(
                    self.create_url(f"/{self.chat.id}/history"),
                    json={"upsert": {"a1": {"content": "first"}}},
                )
            with mock_webui_user(id="2"):
                response = self.fast_api_client.post(
                    self.create_url(f"/{self.chat.id}/history"),
                    json={
                        "upsert": {"a1": {"content": "edited"}},
                        "expected_revision": 0,
                    },
                )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert isinstance(detail, dict)
        assert "revision" in detail
        assert "another user has edited the chat" in detail["message"].lower()
        assert "409" not in detail["message"]

    def test_history_write_error_is_not_chat_not_found(self, monkeypatch):
        def fail(*_args, **_kwargs):
            return None, "error"

        monkeypatch.setattr(self.chats, "apply_history_patch", fail)
        with mock_webui_user(id="2"):
            response = self.fast_api_client.post(
                self.create_url(f"/{self.chat.id}/history"),
                json={"upsert": {"a1": {"content": "x"}}},
            )
        text = str(response.json().get("detail", "")).lower()
        assert response.status_code >= 400
        assert "not found" not in text
        assert "save" in text or "try again" in text or "failed" in text

    def test_turn_without_a_saved_chat_id_is_a_clear_400(self):
        with mock_webui_user(id="2"):
            response = self.fast_api_client.post(
                "/api/chat/completions",
                json={
                    "model": "missing",
                    "model_item": {"direct": True, "id": "missing"},
                    "turn": {
                        "parent_id": "a1",
                        "user_message": {"id": "u2", "content": "hi"},
                        "assistant_message": {"id": "a2", "content": ""},
                    },
                },
            )
        assert response.status_code == 400
        detail = response.json().get("detail")
        text = detail if isinstance(detail, str) else str(detail)
        assert "saved chat id" in text.lower()

    def test_failed_delete_does_not_tell_clients_the_chat_is_gone(self, monkeypatch):
        published = []

        async def capture(chat):
            published.append(chat.id)

        monkeypatch.setattr(
            "open_webui.utils.chat_realtime.publish_chat_removed", capture
        )

        def fail(_id, _user_id=None):
            raise RuntimeError("disk full")

        monkeypatch.setattr(self.chats, "delete_chat_by_id", fail)
        monkeypatch.setattr(self.chats, "delete_chat_by_id_and_user_id", fail)
        with mock_webui_user(id="2"):
            response = self.fast_api_client.delete(self.create_url(f"/{self.chat.id}"))
        assert response.status_code >= 400
        assert published == []
        assert self.chats.get_chat_by_id(self.chat.id) is not None


class TestChatOwnershipOnCompletion(AbstractPostgresTest):
    BASE_PATH = "/api/v1/chats"

    def setup_method(self):
        super().setup_method()
        from open_webui.models.chats import ChatForm, Chats

        self.chats = Chats
        self.chat = Chats.insert_new_chat("owner", ChatForm(chat=_tree()))

    def _post(self, path, body):
        with mock_webui_user(id="intruder"):
            return self.fast_api_client.post(path, json=body)

    def test_completion_into_someone_elses_chat_is_refused_and_writes_nothing(self):
        before = self.chats.get_chat_by_id(self.chat.id).chat
        response = self._post(
            "/api/chat/completions",
            {
                "model": "x",
                "model_item": {"direct": True, "id": "x"},
                "chat_id": self.chat.id,
                "id": "a1",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        assert response.status_code == 401
        assert self.chats.get_chat_by_id(self.chat.id).chat == before

    def test_outlet_and_action_into_someone_elses_chat_are_refused(self):
        body = {"model": "x", "chat_id": self.chat.id, "id": "a1", "messages": []}
        assert self._post("/api/chat/completed", body).status_code == 401
        assert self._post("/api/chat/actions/any", body).status_code == 401
