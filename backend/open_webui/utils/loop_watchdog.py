"""Greppable event-loop stalls in the running app: `loop-watchdog`.

A task on the loop asks to wake every CHECK_INTERVAL_S and measures how late
each wake-up is. Lateness is time the loop spent on one thing without
yielding, while /health, sockets, and every other request waited.

The task can only see a stall after it ends, so a thread watches the task's
last wake-up and, once the loop has been stuck for the stall threshold, logs
the loop thread's stack: the code holding it. Code that holds the GIL in C
(json.dumps, pydantic serialization) keeps that thread out too, so for those
the stack is taken just after the C call returns.

Per wake-up the loop does a clock read and a few comparisons, and the thread
does the same; it logs only on a stall and once per summary interval.

A full GC pass holds the GIL, so it stalls the loop from any thread. Passes
slower than GC_LOG_S are logged with their thread, and once per
CENSUS_INTERVAL_S the thread logs how many objects the collector tracks and,
from a sample, which types they are.
"""

import asyncio
import collections
import gc
import logging
import sys
import threading
import time
import traceback
from contextlib import suppress

log = logging.getLogger(__name__)

PREFIX = "loop-watchdog"
CHECK_INTERVAL_S = 0.1
SUMMARY_INTERVAL_S = 60.0
# Lateness below this is timer jitter, not a stall.
STALL_FLOOR_S = 0.002
GC_LOG_S = 0.1
CENSUS_INTERVAL_S = 3600.0
# Type every Nth tracked object: a full count would hold the GIL several times longer.
CENSUS_SAMPLE = 100
CENSUS_TOP = 25


class LoopWatchdog:
    def __init__(
        self,
        stall_s: float,
        check_interval_s: float = CHECK_INTERVAL_S,
        summary_interval_s: float = SUMMARY_INTERVAL_S,
    ):
        self.stall_s = stall_s
        self.check_interval_s = check_interval_s
        self.summary_interval_s = summary_interval_s
        self._last_wake = time.monotonic()
        self._loop_thread_id: int | None = None
        self._stop = threading.Event()
        self._task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None
        self._gc_started = 0.0
        # Filled by the GC callback, logged from the loop: logging inside a
        # collection could need a lock the collecting thread already holds.
        self._slow_gcs: collections.deque = collections.deque(maxlen=100)

    def start(self) -> None:
        """Start on the loop to watch."""
        self._loop_thread_id = threading.get_ident()
        self._last_wake = time.monotonic()
        gc.callbacks.append(self._on_gc)
        self._task = asyncio.create_task(self._measure())
        self._thread = threading.Thread(target=self._watch, name=PREFIX, daemon=True)
        self._thread.start()

    async def stop(self) -> None:
        with suppress(ValueError):
            gc.callbacks.remove(self._on_gc)
        self._stop.set()
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        await asyncio.to_thread(self._thread.join)

    async def _measure(self) -> None:
        interval = self.check_interval_s
        window_start = time.monotonic()
        worst = blocked = 0.0
        stalls = 0
        while True:
            due = time.monotonic() + interval
            await asyncio.sleep(interval)
            now = time.monotonic()
            self._last_wake = now
            while self._slow_gcs:
                log.warning(
                    "%s gc gen=%d %.3fs collected=%d thread=%s",
                    PREFIX,
                    *self._slow_gcs.popleft(),
                )
            late = now - due
            if late > STALL_FLOOR_S:
                blocked += late
                worst = max(worst, late)
                if late >= self.stall_s:
                    stalls += 1
                    log.warning("%s stall %.3fs", PREFIX, late)
            window = now - window_start
            if window >= self.summary_interval_s:
                log.info(
                    "%s summary window=%.0fs max_lag_ms=%.1f blocked_pct=%.2f stalls=%d",
                    PREFIX,
                    window,
                    worst * 1000,
                    100 * blocked / window,
                    stalls,
                )
                window_start = now
                worst = blocked = 0.0
                stalls = 0

    def _on_gc(self, phase: str, info: dict) -> None:
        if phase == "start":
            self._gc_started = time.perf_counter()
            return
        took = time.perf_counter() - self._gc_started
        if took >= GC_LOG_S:
            self._slow_gcs.append(
                (
                    info["generation"],
                    took,
                    info["collected"],
                    threading.current_thread().name,
                )
            )

    def _census(self) -> None:
        started = time.perf_counter()
        # Frozen objects are not in it: the GC skips them too.
        tracked = gc.get_objects()
        sample = collections.Counter(type(o) for o in tracked[::CENSUS_SAMPLE])
        total = len(tracked)
        del tracked
        top = ", ".join(
            f"{t.__module__}.{t.__qualname__}={n * CENSUS_SAMPLE}"
            for t, n in sample.most_common(CENSUS_TOP)
        )
        log.info(
            "%s heap tracked=%d frozen=%d census_s=%.3f top: %s",
            PREFIX,
            total,
            gc.get_freeze_count(),
            time.perf_counter() - started,
            top,
        )

    def _watch(self) -> None:
        reported = None
        next_census = time.monotonic() + CENSUS_INTERVAL_S
        while True:
            if time.monotonic() >= next_census:
                self._census()
                next_census = time.monotonic() + CENSUS_INTERVAL_S
            last = self._last_wake
            # Sleep until the loop would be stalled if it never woke again.
            wait = last + self.check_interval_s + self.stall_s - time.monotonic()
            if wait > 0 or last == reported:
                # One stack per stall: the stall is the wake-up the loop missed.
                if self._stop.wait(max(wait, self.check_interval_s)):
                    return
                continue
            reported = last
            stuck = time.monotonic() - last - self.check_interval_s
            frame = sys._current_frames().get(self._loop_thread_id)
            stack = "".join(traceback.format_stack(frame)) if frame else ""
            log.warning(
                "%s loop held %.3fs so far, loop thread stack:\n%s",
                PREFIX,
                stuck,
                stack,
            )
