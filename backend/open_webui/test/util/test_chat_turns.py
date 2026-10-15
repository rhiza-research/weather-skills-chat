import unittest

from open_webui.utils.chat_turns import messages_for_model


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


if __name__ == "__main__":
    unittest.main()
