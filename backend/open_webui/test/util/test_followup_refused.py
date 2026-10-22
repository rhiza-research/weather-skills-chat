"""A follow-up model call refused after a tool ran ends the reply with its error."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from starlette.responses import StreamingResponse

import open_webui.utils.middleware as mw
from open_webui.models.usage import ORG_LIMIT_MESSAGE


def _sse(*chunks):
    async def body():
        for chunk in chunks:
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(body(), media_type="text/event-stream")


def _tool_call_stream():
    return _sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {"name": "echo", "arguments": "{}"},
                            }
                        ]
                    }
                }
            ]
        }
    )


class FollowupRefusedTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []

        async def emit(event):
            self.events.append(event)

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
        self.save_final_reply = AsyncMock(return_value=True)

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
            patch.object(
                mw,
                "generate_chat_completion",
                AsyncMock(side_effect=HTTPException(429, detail=ORG_LIMIT_MESSAGE)),
            ),
            patch(
                "open_webui.utils.chat_realtime.save_final_reply",
                self.save_final_reply,
            ),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def test_usage_limit_on_followup_clears_waiting_and_shows_error(self):
        heartbeat = mw.WaitingResponseHeartbeat(
            mw.get_event_emitter(self.metadata)
        )
        await mw.process_chat_response(
            MagicMock(),
            _tool_call_stream(),
            self.form_data,
            self.user,
            self.metadata,
            {"id": "m"},
            [],
            {},
            detach=False,
            waiting_heartbeat=heartbeat,
        )

        self.assertFalse(heartbeat.is_active)
        waiting = [
            e["data"]
            for e in self.events
            if e.get("type") == "status"
            and e["data"].get("action") == mw.WAITING_RESPONSE_ACTION
        ]
        self.assertTrue(waiting[-1]["done"])
        self.assertTrue(waiting[-1].get("hidden"))

        final = [
            e["data"]
            for e in self.events
            if e.get("type") == "chat:completion" and e["data"].get("done")
        ][-1]
        self.assertEqual(final["error"], {"content": ORG_LIMIT_MESSAGE})

        saved_patch = self.save_final_reply.await_args.args[2]
        self.assertTrue(saved_patch["done"])
        self.assertEqual(saved_patch["error"], {"content": ORG_LIMIT_MESSAGE})


class ModelCallErrorMessageTest(unittest.TestCase):
    def test_http_detail_without_status(self):
        e = HTTPException(429, detail=ORG_LIMIT_MESSAGE)
        self.assertEqual(mw.model_call_error_message(e), ORG_LIMIT_MESSAGE)

    def test_other_exception(self):
        self.assertEqual(mw.model_call_error_message(ValueError("boom")), "boom")


if __name__ == "__main__":
    unittest.main()
