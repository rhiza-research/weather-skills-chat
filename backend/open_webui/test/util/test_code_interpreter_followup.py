"""Code interpreter follow-up messages must end on a user turn."""

from __future__ import annotations

import unittest
from pathlib import Path

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


class WebSearchBuiltinToolTest(unittest.TestCase):
    def test_off_unless_chat_enables_it(self):
        from types import SimpleNamespace

        from open_webui.config import DEFAULT_WEB_SEARCH_TOOL_DESCRIPTION
        from open_webui.utils.builtin_tools import get_builtin_tools

        off = get_builtin_tools({"__metadata__": {"features": {}}})
        self.assertNotIn("web_search", off)

        disabled = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    config=SimpleNamespace(
                        ENABLE_WEB_SEARCH=False,
                        WEB_SEARCH_TOOL_DESCRIPTION="",
                    )
                )
            )
        )
        hidden = get_builtin_tools(
            {
                "__metadata__": {"features": {"web_search": True}},
                "__request__": disabled,
            }
        )
        self.assertNotIn("web_search", hidden)

        enabled = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    config=SimpleNamespace(
                        ENABLE_WEB_SEARCH=True,
                        WEB_SEARCH_TOOL_DESCRIPTION="  Custom search guidance.  ",
                    )
                )
            )
        )
        tools = get_builtin_tools(
            {
                "__metadata__": {"features": {"web_search": True}},
                "__request__": enabled,
            }
        )
        spec = tools["web_search"]["spec"]
        self.assertEqual(spec["name"], "web_search")
        self.assertEqual(spec["description"], "Custom search guidance.")
        self.assertIn("queries", spec["parameters"]["properties"])

        defaulted = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    config=SimpleNamespace(
                        ENABLE_WEB_SEARCH=True,
                        WEB_SEARCH_TOOL_DESCRIPTION="   ",
                    )
                )
            )
        )
        tools = get_builtin_tools(
            {
                "__metadata__": {"features": {"web_search": True}},
                "__request__": defaulted,
            }
        )
        self.assertEqual(
            tools["web_search"]["spec"]["description"],
            DEFAULT_WEB_SEARCH_TOOL_DESCRIPTION,
        )

    def test_queries_follow_concurrency_and_result_count(self):
        import asyncio
        import json
        import threading
        import time
        from types import SimpleNamespace
        from unittest.mock import patch

        from open_webui.utils import builtin_tools

        state = {"current": 0, "peak": 0}
        lock = threading.Lock()
        loaded = []

        class Hit:
            def __init__(self, link):
                self.link = link
                self.title = link
                self.snippet = "snippet"

        class Doc:
            def __init__(self, url):
                self.page_content = "page"
                self.metadata = {"source": url, "title": url}

        class Loader:
            def __init__(self, urls, **_kwargs):
                self.urls = list(urls)

            async def aload(self):
                loaded.append(self.urls)
                return [Doc(url) for url in self.urls]

        def fake_search(_request, engine, query):
            self.assertEqual(engine, "brave")
            with lock:
                state["current"] += 1
                state["peak"] = max(state["peak"], state["current"])
            time.sleep(0.05)
            with lock:
                state["current"] -= 1
            return [Hit(f"https://example.com/{query}/{i}") for i in range(5)]

        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    config=SimpleNamespace(
                        WEB_SEARCH_ENGINE="brave",
                        WEB_SEARCH_RESULT_COUNT=2,
                        WEB_SEARCH_CONCURRENT_REQUESTS=2,
                        ENABLE_WEB_LOADER_SSL_VERIFICATION=True,
                        WEB_SEARCH_TRUST_ENV=False,
                    )
                )
            )
        )

        with (
            patch(
                "open_webui.routers.retrieval.search_web",
                side_effect=fake_search,
            ),
            patch(
                "open_webui.retrieval.web.utils.get_web_loader",
                side_effect=Loader,
            ),
        ):
            raw = asyncio.run(
                builtin_tools.web_search(
                    ["a", "b", "c", "d"],
                    __request__=request,
                )
            )

        payload = json.loads(raw)
        self.assertEqual([item["query"] for item in payload["results"]], ["a", "b", "c", "d"])
        self.assertEqual(state["peak"], 2)
        self.assertTrue(loaded)
        self.assertTrue(all(len(urls) == 2 for urls in loaded))
        self.assertTrue(all(len(item["pages"]) == 2 for item in payload["results"]))


class AsPathListTest(unittest.TestCase):
    def test_coerces_string_and_list(self):
        from open_webui.utils.builtin_tools import _as_path_list

        self.assertEqual(_as_path_list(None), [])
        self.assertEqual(_as_path_list("a.csv"), ["a.csv"])
        self.assertEqual(_as_path_list(["a.csv", " b.zarr ", ""]), ["a.csv", "b.zarr"])


class EmailHelpersTest(unittest.TestCase):
    def test_as_email_list_and_validation(self):
        from open_webui.utils.builtin_tools import _as_email_list, _validate_emails

        emails = _as_email_list(["A@EXAMPLE.com", "b@example.com", "a@example.com", ""])
        self.assertEqual(emails, ["a@example.com", "b@example.com"])
        valid, invalid = _validate_emails(["ok@example.com", "bad-email"])
        self.assertEqual(valid, ["ok@example.com"])
        self.assertEqual(invalid, ["bad-email"])

    def test_send_email_builtin_is_available(self):
        from open_webui.utils.builtin_tools import get_builtin_tools

        tools = get_builtin_tools({"__metadata__": {"features": {}}})
        self.assertIn("send_email", tools)
        self.assertEqual(tools["send_email"]["spec"]["name"], "send_email")
        params = tools["send_email"]["spec"]["parameters"]["properties"]
        self.assertIn("attachments", params)

    def test_allowed_recipients_include_organization_members(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import patch

        from open_webui.utils.builtin_tools import (
            _allowed_email_recipients_for_user,
            list_email_recipients,
        )

        directory = {
            "self": {"email": "me@example.com", "name": "Me"},
            "organizations": [
                {
                    "organization_id": "org1",
                    "organization_name": "Field Team",
                    "members": [
                        {
                            "email": "me@example.com",
                            "name": "Me",
                            "role": "admin",
                            "is_self": True,
                        },
                        {
                            "email": "ada@example.com",
                            "name": "Ada",
                            "role": "user",
                            "is_self": False,
                        },
                    ],
                }
            ],
        }
        with patch(
            "open_webui.utils.builtin_tools._email_recipient_directory",
            return_value=directory,
        ):
            allowed = _allowed_email_recipients_for_user("user", None)
        self.assertEqual(allowed, {"me@example.com", "ada@example.com"})

        with (
            patch(
                "open_webui.utils.builtin_tools.Users.get_user_by_id",
                return_value=SimpleNamespace(id="user", email="me@example.com"),
            ),
            patch(
                "open_webui.utils.builtin_tools._email_recipient_directory",
                return_value=directory,
            ),
        ):
            listed = asyncio.run(list_email_recipients(__user__={"id": "user"}))
        self.assertIn("ada@example.com", listed)
        self.assertIn("Field Team", listed)
        self.assertNotIn("No organization member email addresses found.", listed)


class EmailAttachmentTest(unittest.TestCase):
    def test_load_file_attachment(self):
        import tempfile
        from unittest.mock import patch

        from open_webui.utils import artifacts
        from open_webui.utils.builtin_tools import _load_email_attachments

        with tempfile.TemporaryDirectory() as tmp:
            chat_id = "test-chat-email"
            root = Path(tmp) / chat_id
            root.mkdir(parents=True)
            (root / "intermediate_results").mkdir()
            plot = root / "plots" / "map.png"
            plot.parent.mkdir(parents=True)
            plot.write_bytes(b"\x89PNG\r\n")

            with patch.object(artifacts, "ARTIFACTS_DIR", Path(tmp)):
                loaded, notes = _load_email_attachments(chat_id, ["plots/map.png"])

        self.assertEqual(len(loaded), 1)
        filename, data, maintype, subtype = loaded[0]
        self.assertEqual(filename, "plots_map.png")
        self.assertEqual(data, b"\x89PNG\r\n")
        self.assertEqual(maintype, "image")
        self.assertEqual(subtype, "png")
        self.assertIn("plots/map.png", notes[0])

    def test_missing_attachment_raises(self):
        import tempfile
        from unittest.mock import patch

        from open_webui.utils import artifacts
        from open_webui.utils.builtin_tools import _load_email_attachments

        with tempfile.TemporaryDirectory() as tmp:
            chat_id = "test-chat-email-missing"
            (Path(tmp) / chat_id).mkdir()
            with patch.object(artifacts, "ARTIFACTS_DIR", Path(tmp)):
                with self.assertRaises(FileNotFoundError):
                    _load_email_attachments(chat_id, ["missing.png"])


if __name__ == "__main__":
    unittest.main()
