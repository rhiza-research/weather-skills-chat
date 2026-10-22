"""Streamed replies (#62): the reply that restarted prod at 16:39 UTC on 2026-10-21.

An agent turn keeps every tool call and result in one assistant message. For
each streamed delta the server rebuilt that whole message, walked it one
character at a time to repair <details> tags, and sent all of it, on the
event loop and without yielding while deltas were buffered.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.responses import StreamingResponse

from perf_harness import LoopProbe, check_budget, record

ROUNDS = 38  # tool rounds before the final reply (prod: 38)
FINAL_DELTAS = 300
RESULT = "row 12.5 mm; " * 500  # ~6.5 KB per tool result
ARGUMENTS = json.dumps({"bbox": "4,33,-5,42", "notes": "n" * 800})


def _sse(*chunks):
    async def body():
        for chunk in chunks:
            yield f"data: {json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(body(), media_type="text/event-stream")


def _tool_call(i):
    return _sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": f"call_{i}",
                                "function": {"name": "fetch", "arguments": ARGUMENTS},
                            }
                        ]
                    }
                }
            ]
        }
    )


def _reply(deltas):
    return _sse(*({"choices": [{"delta": {"content": f"word{i} "}}]} for i in range(deltas)))


def test_final_reply_of_a_long_agent_turn(tmp_path):
    import open_webui.utils.middleware as mw

    async def emit(event):
        # socket.io JSON-encodes every event for each tab watching the chat.
        json.dumps(event)

    async def fetch(**kwargs):
        return RESULT

    metadata = {
        "chat_id": "chat-perf",
        "message_id": "msg-perf",
        "session_id": "sess-perf",
        "tools": {
            "fetch": {
                "spec": {"name": "fetch", "parameters": {"properties": {}}},
                "callable": fetch,
            }
        },
    }
    user = SimpleNamespace(id="perf-user", email="perf@example.com", name="Perf", role="user")
    follow_ups = [_tool_call(i) for i in range(1, ROUNDS)] + [_reply(FINAL_DELTAS)]

    async def run():
        async with LoopProbe() as probe:
            await mw.process_chat_response(
                MagicMock(),
                _tool_call(0),
                {"model": "weather-agent", "messages": [], "tools": []},
                user,
                metadata,
                {"id": "weather-agent"},
                [],
                {},
                detach=False,
            )
        return probe.stats

    chats = MagicMock(
        **{
            "get_messages_by_chat_id.return_value": {},
            "get_chat_title_by_id.return_value": "Weekly rainfall",
            # One read of the whole chat at the end of the turn (#75).
            "get_chat_by_id.return_value": SimpleNamespace(
                chat={"title": "Weekly rainfall", "history": {"messages": {}}}
            ),
            "get_chat_revision.return_value": 1,
            "get_message_by_id_and_message_id.return_value": {},
        }
    )
    with patch.object(mw, "get_event_emitter", return_value=emit), patch.object(
        mw, "get_event_call", return_value=AsyncMock()
    ), patch.object(mw, "Chats", chats), patch.object(
        mw, "get_sorted_filter_ids", return_value=[]
    ), patch.object(
        mw, "get_active_status_by_user_id", return_value=True
    ), patch.object(
        mw, "generate_chat_completion", AsyncMock(side_effect=follow_ups)
    ), patch(
        "open_webui.utils.chat_realtime.save_final_reply", AsyncMock(return_value=True)
    ):
        stats = asyncio.run(run())

    record(f"stream: {ROUNDS}-round turn, {FINAL_DELTAS}-delta final reply", stats)
    # The run is short once the loop is fixed, so only the longest stall is
    # a stable measure here.
    check_budget(stats, max_lag_ms=150)
