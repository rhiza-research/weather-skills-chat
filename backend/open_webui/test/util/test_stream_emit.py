"""Streamed replies: batched sends, a loop that yields, and a fast details repair."""

import asyncio
import json
import random
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.responses import StreamingResponse

import open_webui.utils.middleware as mw


def _reference_repair(content: str) -> str:
    """The character-by-character version this replaced, kept as the reference."""
    if not content or "<details" not in content:
        return content
    out = []
    depth = 0
    i = 0
    n = len(content)
    open_tag = "<details"
    close_tag = "</details>"
    while i < n:
        if content.startswith(open_tag, i):
            if depth > 0:
                out.append(f"\n{close_tag}\n")
                depth = 0
            out.append(open_tag)
            depth += 1
            i += len(open_tag)
            continue
        if content.startswith(close_tag, i):
            out.append(close_tag)
            depth = max(0, depth - 1)
            i += len(close_tag)
            continue
        out.append(content[i])
        i += 1
    while depth > 0:
        out.append(f"\n{close_tag}")
        depth -= 1
    return "".join(out)


class RepairUnclosedDetailsTest(unittest.TestCase):
    def test_matches_the_reference_on_random_markup(self):
        rng = random.Random(7)
        pieces = [
            "<details",
            "</details>",
            '<details type="reasoning" done="true">',
            "<summary>Thought</summary>",
            "</detail",
            "<detai",
            ">",
            "\n",
            "text ",
            "é",
            "",
        ]
        for _ in range(3000):
            sample = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 25)))
            self.assertEqual(mw.repair_unclosed_details(sample), _reference_repair(sample), repr(sample))

    def test_closes_an_open_block_before_its_sibling(self):
        src = '<details type="reasoning">\nthinking\n<details type="tool_calls">x</details>'
        self.assertEqual(
            mw.repair_unclosed_details(src),
            '<details type="reasoning">\nthinking\n\n</details>\n<details type="tool_calls">x</details>',
        )

    def test_text_without_details_is_returned_as_is(self):
        self.assertEqual(mw.repair_unclosed_details("plain"), "plain")
        self.assertEqual(mw.repair_unclosed_details(""), "")


def _text_stream(n: int, *, mark=None):
    async def body():
        for i in range(n):
            if mark is not None:
                mark.append(i)
            yield f'data: {json.dumps({"choices": [{"delta": {"content": f"w{i} "}}]})}\n\n'
        yield "data: [DONE]\n\n"

    return StreamingResponse(body(), media_type="text/event-stream")


class StreamEmitTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.events = []

        async def emit(event):
            self.events.append(event)

        self.metadata = {"chat_id": "chat-1", "message_id": "msg-1", "session_id": "sess-1"}
        self.user = SimpleNamespace(id="u1", email="u@example.com", name="U", role="user")
        patches = [
            patch.object(mw, "get_event_emitter", return_value=emit),
            patch.object(mw, "get_event_call", return_value=AsyncMock()),
            patch.object(
                mw,
                "Chats",
                MagicMock(
                    **{
                        "get_chat_by_id.return_value": SimpleNamespace(
                            chat={"title": "Title", "history": {"messages": {}}}
                        ),
                        "get_chat_revision.return_value": 1,
                        "get_message_by_id_and_message_id.return_value": {},
                    }
                ),
            ),
            patch.object(mw, "get_sorted_filter_ids", return_value=[]),
            patch.object(mw, "get_active_status_by_user_id", return_value=True),
            patch("open_webui.utils.chat_realtime.save_final_reply", AsyncMock(return_value=True)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    async def _run(self, response):
        await mw.process_chat_response(
            MagicMock(),
            response,
            {"model": "m", "messages": [], "tools": []},
            self.user,
            self.metadata,
            {"id": "m"},
            [],
            {},
            detach=False,
        )

    def _content_sends(self):
        return [
            e["data"]["content"]
            for e in self.events
            if e.get("type") == "chat:completion"
            and "content" in e.get("data", {})
            and not e["data"].get("done")
        ]

    async def test_sends_are_batched_and_the_last_one_is_complete(self):
        with patch.object(mw, "STREAM_EMIT_INTERVAL_S", 3600):
            await self._run(_text_stream(300))
        sends = self._content_sends()
        # The first delta goes out at once; the rest wait for the end of the stream.
        self.assertEqual(len(sends), 2)
        self.assertEqual(sends[0].strip(), "w0")
        self.assertIn("w299", sends[-1])
        done = [e["data"] for e in self.events if e.get("type") == "chat:completion" and e["data"].get("done")]
        self.assertIn("w299", done[-1]["content"])

    async def test_without_a_limit_every_delta_is_sent(self):
        with patch.object(mw, "STREAM_EMIT_INTERVAL_S", 0):
            await self._run(_text_stream(50))
        self.assertEqual(len(self._content_sends()), 50)

    async def test_a_buffered_burst_lets_other_tasks_run(self):
        ticks = []
        consumed = []

        async def ticker():
            while True:
                ticks.append(len(consumed))
                await asyncio.sleep(0)

        task = asyncio.create_task(ticker())
        await asyncio.sleep(0)
        ticks.clear()
        try:
            with patch.object(mw, "STREAM_YIELD_INTERVAL_S", 0):
                await self._run(_text_stream(200, mark=consumed))
        finally:
            task.cancel()
        # The ticker ran while the stream was still being read, not only after.
        # The ticker ran throughout the burst, not once or only after it.
        during = {seen for seen in ticks if 0 < seen < 200}
        self.assertGreater(len(during), 50)


if __name__ == "__main__":
    unittest.main()
