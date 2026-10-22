"""A call to a tool the message does not offer returns an error, not null."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.responses import StreamingResponse

import open_webui.utils.middleware as mw


def _sse(*chunks):
    async def body():
        for chunk in chunks:
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(body(), media_type="text/event-stream")


def _tool_call_stream(name):
    return _sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": name,
                                    "arguments": json.dumps({"argv": ["--help"]}),
                                },
                            }
                        ]
                    }
                }
            ]
        }
    )


class UnavailableToolTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        async def emit(event):
            return None

        async def echo():
            return "ok"

        self.metadata = {
            "chat_id": "chat-1",
            "message_id": "msg-1",
            "session_id": "sess-1",
            "tools": {
                "echo": {
                    "spec": {"name": "echo", "parameters": {"properties": {}}},
                    "callable": echo,
                }
            },
        }
        self.form_data = {"model": "m", "messages": [], "tools": []}
        self.user = SimpleNamespace(
            id="u1", email="u@example.com", name="U", role="user"
        )
        # Stop after the tool runs; the follow-up request carries its result.
        self.followup = AsyncMock(side_effect=HTTPException(500, detail="stop"))

        patches = [
            patch.object(mw, "get_event_emitter", return_value=emit),
            patch.object(mw, "get_event_call", return_value=AsyncMock()),
            patch.object(mw, "Chats", MagicMock(**{
                "get_chat_by_id.return_value": SimpleNamespace(
                    chat={"title": "Title", "history": {"messages": {}}}
                ),
                "get_chat_revision.return_value": 1,
                "get_message_by_id_and_message_id.return_value": {},
            })),
            patch.object(mw, "get_sorted_filter_ids", return_value=[]),
            patch.object(mw, "get_active_status_by_user_id", return_value=True),
            patch.object(mw, "generate_chat_completion", self.followup),
            patch(
                "open_webui.utils.chat_realtime.save_final_reply",
                AsyncMock(return_value=1),
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def _tool_result(self, name):
        await mw.process_chat_response(
            MagicMock(),
            _tool_call_stream(name),
            self.form_data,
            self.user,
            self.metadata,
            {"id": "m"},
            [],
            {},
            detach=False,
        )
        messages = self.followup.await_args.args[1]["messages"]
        results = [m for m in messages if m.get("role") == "tool"]
        self.assertEqual(len(results), 1)
        return results[0]["content"]

    async def test_unoffered_tool_returns_clear_error(self):
        content = await self._tool_result("plot")
        self.assertEqual(content, mw.unavailable_tool_message("plot"))
        self.assertIn("`plot` is not available", content)
        self.assertIn("wrench button", content)

    async def test_offered_tool_still_runs(self):
        self.assertEqual(await self._tool_result("echo"), "ok")


class UnavailableToolMessageTest(unittest.TestCase):
    def test_names_the_tool(self):
        self.assertTrue(
            mw.unavailable_tool_message("plot").startswith(
                "Error: `plot` is not available"
            )
        )

    def test_without_a_name(self):
        self.assertTrue(
            mw.unavailable_tool_message("").startswith(
                "Error: That tool is not available"
            )
        )


if __name__ == "__main__":
    unittest.main()
