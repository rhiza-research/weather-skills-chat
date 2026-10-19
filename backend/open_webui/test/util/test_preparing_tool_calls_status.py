"""Status line while the model streams tool-call arguments."""

import asyncio
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from open_webui.utils import middleware
from open_webui.utils.middleware import PreparingToolCallsStatus


class PreparingToolCallsStatusTest(IsolatedAsyncioTestCase):
    def setUp(self):
        self.events = []

        async def emit(event):
            self.events.append(event["data"])

        self.status = PreparingToolCallsStatus(emit)

    def _descriptions(self):
        return [e["description"] for e in self.events if not e.get("hidden")]

    async def test_shows_a_timer_while_the_calls_stream_in(self):
        clock = {"t": 1000.0}
        with patch.object(middleware.time, "time", side_effect=lambda: clock["t"]), patch.object(
            middleware, "WAITING_RESPONSE_INTERVAL_S", 0.01
        ):
            await self.status.start()
            clock["t"] = 1003.4
            for _ in range(50):
                if any("(3s)" in d for d in self._descriptions()):
                    break
                await asyncio.sleep(0.01)
            await self.status.finish()
        self.assertEqual(self.events[0]["description"], "Preparing tool calls… (0s)")
        self.assertEqual(self.events[0]["action"], "preparing_tool_calls")
        self.assertFalse(self.events[0]["done"])
        self.assertIn("Preparing tool calls… (3s)", self._descriptions())

    async def test_finish_leaves_the_line_until_clear_hides_it_once(self):
        await self.status.start()
        await self.status.finish()
        shown = len(self.events)
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.events), shown, "kept ticking after the stream ended")
        self.assertFalse(any(e.get("hidden") for e in self.events))

        await self.status.clear()
        await self.status.clear()
        hidden = [e for e in self.events if e.get("hidden")]
        self.assertEqual(len(hidden), 1)
        self.assertTrue(hidden[0]["done"])
        self.assertEqual(hidden[0]["action"], "preparing_tool_calls")

    async def test_clear_without_tool_calls_emits_nothing(self):
        await self.status.clear()
        self.assertEqual(self.events, [])

    async def test_shows_again_for_the_next_batch(self):
        await self.status.start()
        await self.status.finish()
        await self.status.clear()
        await self.status.start()
        await self.status.finish()
        await self.status.clear()
        self.assertEqual(sum(1 for e in self.events if e.get("hidden")), 2)
