import unittest
from unittest.mock import MagicMock, patch

from open_webui.utils.chat_turns import messages_for_model, store_refused_turn


class MessagesForModelTest(unittest.TestCase):
    def test_linearizes_and_drops_hidden_details_and_empty_assistant(self):
        history = {
            "messages": {
                "u1": {
                    "id": "u1",
                    "parentId": None,
                    "role": "user",
                    "content": "Rain in Kenya?",
                    "childrenIds": ["a1"],
                },
                "a1": {
                    "id": "a1",
                    "parentId": "u1",
                    "role": "assistant",
                    "childrenIds": ["u2"],
                    "content": (
                        '<details type="reasoning" done="true"><summary>Thought</summary>secret</details>'
                        '<details type="tool_calls" done="true" id="t1" name="web_search"></details>'
                        "Done."
                    ),
                },
                "u2": {
                    "id": "u2",
                    "parentId": "a1",
                    "role": "user",
                    "content": "And tomorrow?",
                    "childrenIds": ["a2"],
                },
                "a2": {
                    "id": "a2",
                    "parentId": "u2",
                    "role": "assistant",
                    "content": "",
                    "childrenIds": [],
                },
            }
        }

        messages = messages_for_model(history, "a2")
        self.assertEqual([message["role"] for message in messages], ["user", "assistant", "user"])
        self.assertNotIn("secret", messages[1]["content"])
        self.assertIn('type="tool_calls"', messages[1]["content"])
        self.assertEqual(messages[2]["content"], "And tomorrow?")

    def test_legacy_user_images_are_sent(self):
        history = {
            "messages": {
                "u1": {
                    "id": "u1",
                    "parentId": None,
                    "role": "user",
                    "content": "What is this?",
                    "files": [{"type": "image", "url": "data:image/png;base64,abc"}],
                    "childrenIds": ["a1"],
                },
                "a1": {
                    "id": "a1",
                    "parentId": "u1",
                    "role": "assistant",
                    "content": "A plot.",
                    "childrenIds": [],
                },
            }
        }
        messages = messages_for_model(history, "a1")
        content = messages[0]["content"]
        self.assertIsInstance(content, list)
        self.assertEqual(content[1]["type"], "image_url")

    def test_awaiting_approval_images_are_not_sent(self):
        history = {
            "messages": {
                "u1": {
                    "id": "u1",
                    "parentId": None,
                    "role": "user",
                    "content": "Look at this",
                    "files": [
                        {
                            "type": "image",
                            "url": "data:image/png;base64,abc",
                            "sandboxPath": "photo.png",
                            "awaitingApproval": True,
                        }
                    ],
                    "childrenIds": ["a1"],
                },
                "a1": {
                    "id": "a1",
                    "parentId": "u1",
                    "role": "assistant",
                    "content": "I will ask to read it.",
                    "childrenIds": [],
                },
            }
        }
        messages = messages_for_model(history, "a1")
        self.assertEqual(
            messages[0]["content"],
            "Look at this\n\nThe user uploaded an image at `photo.png`.",
        )

    def test_upload_note_injected_from_files_not_user_text(self):
        history = {
            "messages": {
                "u1": {
                    "id": "u1",
                    "parentId": None,
                    "role": "user",
                    "content": "see this",
                    "files": [
                        {
                            "type": "file",
                            "name": "report.pdf",
                            "sandboxPath": "report.pdf",
                            "awaitingApproval": True,
                        }
                    ],
                    "childrenIds": ["a1"],
                },
                "a1": {
                    "id": "a1",
                    "parentId": "u1",
                    "role": "assistant",
                    "content": "ok",
                    "childrenIds": [],
                },
            }
        }
        messages = messages_for_model(history, "a1")
        self.assertEqual(
            messages[0]["content"],
            "see this\n\nThe user uploaded a file at `report.pdf`.",
        )

    def test_existing_upload_note_is_not_duplicated(self):
        history = {
            "messages": {
                "u1": {
                    "id": "u1",
                    "parentId": None,
                    "role": "user",
                    "content": "The user uploaded an image at `photo.png`.",
                    "files": [
                        {
                            "type": "image",
                            "sandboxPath": "photo.png",
                            "awaitingApproval": True,
                        }
                    ],
                    "childrenIds": ["a1"],
                },
                "a1": {
                    "id": "a1",
                    "parentId": "u1",
                    "role": "assistant",
                    "content": "ok",
                    "childrenIds": [],
                },
            }
        }
        messages = messages_for_model(history, "a1")
        self.assertEqual(messages[0]["content"], "The user uploaded an image at `photo.png`.")



class StoreRefusedTurnTest(unittest.TestCase):
    turn = {
        "expected_revision": 3,
        "user_message": {"id": "u1", "parentId": None, "role": "user", "content": "Hi"},
        "assistant_message": {
            "id": "a1",
            "parentId": "u1",
            "role": "assistant",
            "content": "",
            "done": False,
        },
    }

    @patch("open_webui.utils.chat_turns.can_write_chat", return_value=True)
    @patch("open_webui.utils.chat_turns.Chats")
    def test_reply_is_stored_finished_with_the_error(self, chats, _can_write):
        chats.append_turn.return_value = (MagicMock(), "ok")

        self.assertTrue(store_refused_turn("c1", self.turn, MagicMock(), "Limit reached."))

        chat_id, user_message, assistant_message, expected = chats.append_turn.call_args.args
        self.assertEqual(chat_id, "c1")
        self.assertEqual(user_message["id"], "u1")
        self.assertEqual(assistant_message["id"], "a1")
        self.assertIs(assistant_message["done"], True)
        self.assertEqual(assistant_message["error"], {"content": "Limit reached."})
        self.assertEqual(expected, 3)

    @patch("open_webui.utils.chat_turns.can_write_chat", return_value=False)
    @patch("open_webui.utils.chat_turns.Chats")
    def test_read_only_chat_is_not_written(self, chats, _can_write):
        self.assertFalse(store_refused_turn("c1", self.turn, MagicMock(), "Limit reached."))
        chats.append_turn.assert_not_called()

    @patch("open_webui.utils.chat_turns.can_write_chat", return_value=True)
    @patch("open_webui.utils.chat_turns.Chats")
    def test_write_failure_does_not_raise(self, chats, _can_write):
        chats.append_turn.side_effect = RuntimeError("database down")
        self.assertFalse(store_refused_turn("c1", self.turn, MagicMock(), "Limit reached."))

    def test_malformed_turn_is_ignored(self):
        self.assertFalse(store_refused_turn("c1", {"user_message": {}}, MagicMock(), "x"))


if __name__ == "__main__":
    unittest.main()
