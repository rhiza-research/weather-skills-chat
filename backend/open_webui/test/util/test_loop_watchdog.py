"""The loop watchdog logs stalls, the code holding the loop, and a summary."""

import asyncio
import gc
import time
import unittest
from unittest.mock import MagicMock, patch

from open_webui.utils.loop_watchdog import LoopWatchdog

LOGGER = "open_webui.utils.loop_watchdog"


def hold_the_loop(seconds):
    # Busy, not time.sleep: a sleep releases the GIL, a real stall usually doesn't.
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


class LoopWatchdogTest(unittest.IsolatedAsyncioTestCase):
    def watchdog(self, **kwargs):
        kwargs.setdefault("stall_s", 0.15)
        kwargs.setdefault("check_interval_s", 0.02)
        kwargs.setdefault("summary_interval_s", 60)
        return LoopWatchdog(**kwargs)

    async def test_logs_the_stall_and_the_stack_holding_the_loop(self):
        dog = self.watchdog()
        with self.assertLogs(LOGGER, level="WARNING") as logs:
            dog.start()
            await asyncio.sleep(0.05)
            hold_the_loop(0.4)
            await asyncio.sleep(0.05)
            await dog.stop()

        stalls = [r for r in logs.records if " stall " in r.getMessage()]
        self.assertEqual(len(stalls), 1)
        self.assertGreaterEqual(stalls[0].args[1], 0.35)

        stacks = [r for r in logs.records if "stack" in r.getMessage()]
        self.assertEqual(len(stacks), 1, "one stack per stall")
        self.assertIn("hold_the_loop", stacks[0].getMessage())

    async def test_quiet_loop_logs_no_warnings(self):
        dog = self.watchdog()
        with patch("open_webui.utils.loop_watchdog.log") as log:
            dog.start()
            await asyncio.sleep(0.3)
            await dog.stop()
        log.warning.assert_not_called()

    async def test_short_blocks_are_not_stalls(self):
        dog = self.watchdog()
        with patch("open_webui.utils.loop_watchdog.log") as log:
            dog.start()
            for _ in range(3):
                hold_the_loop(0.05)
                await asyncio.sleep(0.03)
            await dog.stop()
        log.warning.assert_not_called()

    async def test_summary_reports_worst_lag_and_blocked_share(self):
        dog = self.watchdog(summary_interval_s=0.3)
        with self.assertLogs(LOGGER, level="INFO") as logs:
            dog.start()
            await asyncio.sleep(0.05)
            hold_the_loop(0.2)
            await asyncio.sleep(0.2)
            await dog.stop()

        summaries = [
            r.args for r in logs.records if " summary window=" in r.getMessage()
        ]
        self.assertTrue(summaries)
        # The stall's window, not the first: CI once logged a quiet window before it.
        _, window_s, max_lag_ms, blocked_pct, stalls = max(
            summaries, key=lambda a: a[2]
        )
        self.assertGreaterEqual(max_lag_ms, 150)
        self.assertGreater(blocked_pct, 20)
        self.assertEqual(stalls, 1)

    async def test_logs_slow_gc_passes_with_their_thread(self):
        dog = self.watchdog()
        with patch("open_webui.utils.loop_watchdog.GC_LOG_S", 0):
            with self.assertLogs(LOGGER, level="WARNING") as logs:
                dog.start()
                gc.collect()
                await asyncio.sleep(0.05)
                await dog.stop()
        passes = [r.args for r in logs.records if " gc gen=" in r.getMessage()]
        self.assertIn((2, "MainThread"), [(a[1], a[4]) for a in passes])
        self.assertNotIn(dog._on_gc, gc.callbacks)

    async def test_census_logs_tracked_objects_by_type(self):
        dog = self.watchdog()
        with patch("open_webui.utils.loop_watchdog.CENSUS_INTERVAL_S", 0.05):
            with self.assertLogs(LOGGER, level="INFO") as logs:
                dog.start()
                await asyncio.sleep(0.2)
                await dog.stop()
        census = [r for r in logs.records if " heap tracked=" in r.getMessage()]
        self.assertTrue(census)
        self.assertGreater(census[0].args[1], 1000)
        self.assertIn("builtins.dict=", census[0].getMessage())

    async def test_stop_ends_the_thread_and_task(self):
        dog = self.watchdog()
        dog.start()
        await asyncio.sleep(0.05)
        await dog.stop()
        self.assertFalse(dog._thread.is_alive())
        self.assertTrue(dog._task.done())


class LifespanTest(unittest.IsolatedAsyncioTestCase):
    async def lifespan(self, enabled):
        import main

        dog = MagicMock()

        async def stop():
            dog.stopped = True

        dog.stop = stop

        async def no_cleanup():
            return None

        with (
            patch.object(main, "LOOP_WATCHDOG_ENABLED", enabled),
            patch.object(main, "LoopWatchdog", return_value=dog) as cls,
            patch.object(main, "get_langfuse_client"),
            patch.object(main, "start_logger"),
            patch.object(main, "periodic_usage_pool_cleanup", no_cleanup),
            patch.object(main, "ensure_retrieval_models"),
            patch.object(main, "_resync_skill_packs"),
            patch("open_webui.utils.bootstrap.bootstrap_admin_user"),
            patch("open_webui.utils.automation_scheduler.start_scheduler"),
            patch("open_webui.utils.automation_scheduler.shutdown_scheduler"),
            patch.object(main, "shutdown_langfuse", MagicMock()),
            patch.object(main, "gc"),
        ):
            async with main.lifespan(main.app):
                started = dog.start.called
        return cls, started, getattr(dog, "stopped", False)

    async def test_runs_for_the_life_of_the_app_when_enabled(self):
        cls, started, stopped = await self.lifespan(enabled=True)
        cls.assert_called_once()
        self.assertTrue(started)
        self.assertTrue(stopped)

    async def test_not_started_when_disabled(self):
        cls, started, _ = await self.lifespan(enabled=False)
        cls.assert_not_called()
        self.assertFalse(started)


class FreezeAfterStartupTest(unittest.IsolatedAsyncioTestCase):
    async def test_freezes_once_startup_loads_finish_even_if_one_fails(self):
        import main

        order = []

        async def load():
            order.append("load")

        async def fail():
            raise RuntimeError("model download failed")

        with patch.object(main, "gc") as gc_mock:
            gc_mock.collect.side_effect = lambda: order.append("collect")
            gc_mock.freeze.side_effect = lambda: order.append("freeze")
            with self.assertLogs("main", level="ERROR"):
                await main._freeze_after([load(), fail()])
        self.assertEqual(order, ["load", "collect", "freeze"])


if __name__ == "__main__":
    unittest.main()
