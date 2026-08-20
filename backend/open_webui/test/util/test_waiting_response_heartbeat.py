import asyncio
import unittest
from unittest.mock import AsyncMock

from open_webui.utils.middleware import (
    WAITING_RESPONSE_ACTION,
    WaitingResponseHeartbeat,
)


class WaitingResponseHeartbeatTest(unittest.IsolatedAsyncioTestCase):
    async def test_emits_waiting_then_clears_on_activity(self):
        emitter = AsyncMock()
        heartbeat = WaitingResponseHeartbeat(emitter)

        await heartbeat.start()
        self.assertEqual(emitter.await_count, 1)
        first = emitter.await_args.args[0]
        self.assertEqual(first["type"], "status")
        self.assertEqual(first["data"]["action"], WAITING_RESPONSE_ACTION)
        self.assertFalse(first["data"]["done"])

        await heartbeat.mark_activity()
        self.assertGreaterEqual(emitter.await_count, 2)
        last = emitter.await_args.args[0]
        self.assertTrue(last["data"]["done"])
        self.assertTrue(last["data"].get("hidden"))

        # Second clear should not emit again
        count = emitter.await_count
        await heartbeat.stop(clear=True)
        self.assertEqual(emitter.await_count, count)

    async def test_heartbeat_ticks_while_waiting(self):
        emitter = AsyncMock()
        heartbeat = WaitingResponseHeartbeat(emitter)
        heartbeat_interval = 0.05

        # Temporarily speed up ticks for the test
        import open_webui.utils.middleware as mw

        old = mw.WAITING_RESPONSE_INTERVAL_S
        mw.WAITING_RESPONSE_INTERVAL_S = heartbeat_interval
        try:
            await heartbeat.start()
            await asyncio.sleep(heartbeat_interval * 2.5)
            await heartbeat.stop(clear=True)
        finally:
            mw.WAITING_RESPONSE_INTERVAL_S = old

        # start + at least one tick + clear
        self.assertGreaterEqual(emitter.await_count, 3)
        descriptions = [
            call.args[0]["data"]["description"] for call in emitter.await_args_list
        ]
        self.assertTrue(any("Still waiting" in d for d in descriptions))


if __name__ == "__main__":
    unittest.main()
