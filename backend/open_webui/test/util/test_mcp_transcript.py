"""Recording endpoint tool calls into the account's session chat.

Each call is written as an assistant message holding only a tool-call element. A write failure is
logged and not raised.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.mcp.transcript import ASSISTANT_ROLE, record_tool_call

SESSION_ID = "b2c3d4e5-0000-4000-8000-000000000000"


def session(history=None):
    return SimpleNamespace(
        id=SESSION_ID, user_id="account-1", chat={"history": history or {}}
    )


class FirstCallTest(unittest.TestCase):
    def record(self, existing_history=None, stored=None):
        with patch(
            "open_webui.mcp.transcript.Chats.upsert_message_to_chat_by_id_and_message_id"
        ) as upsert, patch(
            "open_webui.mcp.transcript.Chats.get_chat_by_id", return_value=stored
        ):
            record_tool_call(
                session(existing_history),
                name="fetch_rain",
                arguments={"bbox": "0,0,1,1"},
                result={"ok": True},
            )
        return upsert

    def test_one_message_is_written(self):
        upsert = self.record()
        self.assertEqual(upsert.call_count, 1)

    def test_it_is_written_to_the_session(self):
        upsert = self.record()
        self.assertEqual(upsert.call_args.args[0], SESSION_ID)

    def test_it_carries_the_tool_call_element(self):
        upsert = self.record()
        message = upsert.call_args.args[2]
        self.assertIn('<details type="tool_calls"', message["content"])
        self.assertIn("fetch_rain", message["content"])

    def test_it_has_no_parent_when_it_is_the_first(self):
        upsert = self.record()
        self.assertIsNone(upsert.call_args.args[2]["parentId"])

    def test_the_role_is_not_a_typed_prompt(self):
        # The interface renders a user-role message as text the person typed.
        upsert = self.record()
        self.assertEqual(upsert.call_args.args[2]["role"], ASSISTANT_ROLE)

    def test_no_prose_answer_is_written(self):
        upsert = self.record()
        content = upsert.call_args.args[2]["content"]
        self.assertTrue(content.strip().startswith("<details"))
        self.assertTrue(content.strip().endswith("</details>"))


class ChainedCallTest(unittest.TestCase):
    def test_a_later_call_points_back_at_the_previous_one(self):
        history = {"currentId": "first", "messages": {"first": {"childrenIds": []}}}
        stored = SimpleNamespace(chat={"history": history})
        with patch(
            "open_webui.mcp.transcript.Chats.upsert_message_to_chat_by_id_and_message_id"
        ) as upsert, patch(
            "open_webui.mcp.transcript.Chats.get_chat_by_id", return_value=stored
        ):
            record_tool_call(
                session(history), name="plot", arguments={}, result={"ok": True}
            )
        first_message = upsert.call_args_list[0].args[2]
        self.assertEqual(first_message["parentId"], "first")

    def test_the_previous_message_gains_the_new_one_as_a_child(self):
        history = {"currentId": "first", "messages": {"first": {"childrenIds": []}}}
        stored = SimpleNamespace(chat={"history": history})
        with patch(
            "open_webui.mcp.transcript.Chats.upsert_message_to_chat_by_id_and_message_id"
        ) as upsert, patch(
            "open_webui.mcp.transcript.Chats.get_chat_by_id", return_value=stored
        ):
            record_tool_call(
                session(history), name="plot", arguments={}, result={"ok": True}
            )
        parent_write = [
            call for call in upsert.call_args_list if call.args[1] == "first"
        ]
        self.assertEqual(len(parent_write), 1)
        self.assertEqual(len(parent_write[0].args[2]["childrenIds"]), 1)


class NeverRaisesTest(unittest.TestCase):
    def test_a_refusing_store_does_not_raise(self):
        # The tool call's result is returned even when recording it fails.
        with patch(
            "open_webui.mcp.transcript.Chats.upsert_message_to_chat_by_id_and_message_id",
            side_effect=RuntimeError("store down"),
        ):
            record_tool_call(
                session(), name="fetch_rain", arguments={}, result={"ok": True}
            )

    def test_a_missing_session_row_does_not_raise(self):
        history = {"currentId": "first", "messages": {}}
        with patch(
            "open_webui.mcp.transcript.Chats.upsert_message_to_chat_by_id_and_message_id"
        ), patch("open_webui.mcp.transcript.Chats.get_chat_by_id", return_value=None):
            record_tool_call(
                session(history), name="plot", arguments={}, result={"ok": True}
            )


if __name__ == "__main__":
    unittest.main()
