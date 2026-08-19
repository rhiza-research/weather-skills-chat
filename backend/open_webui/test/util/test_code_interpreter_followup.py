"""Code interpreter follow-up messages must end on a user turn."""

from __future__ import annotations

import unittest

from open_webui.utils.middleware import (
    code_interpreter_followup_messages,
    format_code_interpreter_result,
)


def _serialize(blocks, raw=False):
    parts = []
    for block in blocks:
        if block.get("type") == "code_interpreter":
            parts.append(block.get("content", ""))
        else:
            parts.append(block.get("content", ""))
    return "\n".join(p for p in parts if p)


class FormatResultTest(unittest.TestCase):
    def test_stderr_is_visible(self):
        text = format_code_interpreter_result(
            {"stdout": None, "stderr": "NameError: x", "result": None}
        )
        self.assertIn("NameError: x", text)
        self.assertIn("fix the code", text)

    def test_string_exception(self):
        text = format_code_interpreter_result("TimeoutError")
        self.assertIn("TimeoutError", text)


class FollowupMessagesTest(unittest.TestCase):
    def test_output_is_a_user_message(self):
        blocks = [
            {"type": "text", "content": "Let me run this."},
            {
                "type": "code_interpreter",
                "content": "print(1/0)",
                "attributes": {"type": "code", "lang": "python"},
                "output": {"stdout": None, "stderr": "ZeroDivisionError", "result": None},
            },
            {"type": "text", "content": ""},
        ]
        messages = code_interpreter_followup_messages(blocks, _serialize)
        self.assertEqual(messages[-1]["role"], "user")
        self.assertIn("ZeroDivisionError", messages[-1]["content"])
        self.assertEqual(messages[0]["role"], "assistant")
        self.assertIn("print(1/0)", messages[0]["content"])

    def test_always_ends_with_user(self):
        blocks = [{"type": "text", "content": "hello"}]
        messages = code_interpreter_followup_messages(blocks, _serialize)
        self.assertEqual(messages[-1]["role"], "user")


class BuiltinExecuteCodeToolTest(unittest.TestCase):
    def test_gated_on_feature_flag(self):
        from open_webui.utils.builtin_tools import get_builtin_tools

        off = get_builtin_tools({"__metadata__": {"features": {}}})
        self.assertNotIn("execute_code", off)
        on = get_builtin_tools(
            {"__metadata__": {"features": {"code_interpreter": True}}}
        )
        self.assertIn("execute_code", on)
        self.assertEqual(on["execute_code"]["spec"]["name"], "execute_code")
        params = on["execute_code"]["spec"]["parameters"]["properties"]
        self.assertIn("inputs", params)
        self.assertIn("outputs", params)


class AsPathListTest(unittest.TestCase):
    def test_coerces_string_and_list(self):
        from open_webui.utils.builtin_tools import _as_path_list

        self.assertEqual(_as_path_list(None), [])
        self.assertEqual(_as_path_list("a.csv"), ["a.csv"])
        self.assertEqual(_as_path_list(["a.csv", " b.zarr ", ""]), ["a.csv", "b.zarr"])


if __name__ == "__main__":
    unittest.main()
