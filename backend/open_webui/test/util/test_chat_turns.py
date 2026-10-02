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


if __name__ == "__main__":
    unittest.main()
