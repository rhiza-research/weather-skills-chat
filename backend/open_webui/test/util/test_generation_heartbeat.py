import asyncio
import unittest
from unittest.mock import AsyncMock

from open_webui.utils.middleware import (
    GENERATION_HEARTBEAT_ACTION,
    GenerationHeartbeat,
)


class GenerationHeartbeatTest(unittest.IsolatedAsyncioTestCase):
    async def test_emits_hidden_liveness_then_clears_on_stop(self):
        emitter = AsyncMock()
        heartbeat = GenerationHeartbeat(emitter)

        await heartbeat.start()
        self.assertEqual(emitter.await_count, 1)
        first = emitter.await_args.args[0]
        self.assertEqual(first["type"], "status")
        self.assertEqual(first["data"]["action"], GENERATION_HEARTBEAT_ACTION)
        self.assertFalse(first["data"]["done"])
        self.assertTrue(first["data"]["hidden"])

        await heartbeat.stop(clear=True)
        self.assertGreaterEqual(emitter.await_count, 2)
        last = emitter.await_args.args[0]
        self.assertTrue(last["data"]["done"])
        self.assertTrue(last["data"]["hidden"])

        count = emitter.await_count
        await heartbeat.stop(clear=True)
        self.assertEqual(emitter.await_count, count)

    async def test_ticks_while_generation_runs(self):
        emitter = AsyncMock()
        heartbeat = GenerationHeartbeat(emitter)

        import open_webui.utils.middleware as mw

        old = mw.GENERATION_HEARTBEAT_INTERVAL_S
        mw.GENERATION_HEARTBEAT_INTERVAL_S = 0.05
        try:
            await heartbeat.start()
            await asyncio.sleep(0.14)
            await heartbeat.stop(clear=True)
        finally:
            mw.GENERATION_HEARTBEAT_INTERVAL_S = old

        # start + at least one tick + clear
        self.assertGreaterEqual(emitter.await_count, 3)
        actions = [
            call.args[0]["data"]["action"] for call in emitter.await_args_list
        ]
        self.assertTrue(all(a == GENERATION_HEARTBEAT_ACTION for a in actions))


if __name__ == "__main__":
    unittest.main()
