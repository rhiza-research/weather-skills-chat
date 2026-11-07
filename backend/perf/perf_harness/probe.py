"""Measure how long the event loop is held while a scenario runs.

A probe task asks to wake every ``interval`` seconds and records how late each
wake-up is. Lateness is time the loop spent on something else without
yielding: exactly what makes /health, sockets, and every other user wait.
"""

from __future__ import annotations

import asyncio
import gc
import time
from dataclasses import dataclass, field


# Lateness below this is timer jitter, not a stall.
STALL_FLOOR_S = 0.002


@dataclass
class LoopStats:
    duration_s: float = 0.0
    lags_s: list[float] = field(default_factory=list)

    @property
    def max_lag_ms(self) -> float:
        return max(self.lags_s, default=0.0) * 1000

    @property
    def p99_lag_ms(self) -> float:
        if not self.lags_s:
            return 0.0
        ordered = sorted(self.lags_s)
        return ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))] * 1000

    @property
    def blocked_pct(self) -> float:
        """Share of the run the loop spent unable to serve anything else.

        Only stalls over STALL_FLOOR_S count: every timer wake-up is a fraction
        of a millisecond late even on an idle loop, which would otherwise read
        as ~10% blocked at a 5 ms probe interval.
        """
        if self.duration_s <= 0:
            return 0.0
        held = sum(lag for lag in self.lags_s if lag > STALL_FLOOR_S)
        return 100 * held / self.duration_s

    def stalls_over(self, ms: float) -> int:
        return sum(1 for lag in self.lags_s if lag * 1000 > ms)

    def as_dict(self) -> dict:
        return {
            "duration_s": round(self.duration_s, 3),
            "max_lag_ms": round(self.max_lag_ms, 1),
            "p99_lag_ms": round(self.p99_lag_ms, 1),
            "blocked_pct": round(self.blocked_pct, 1),
            "stalls_over_100ms": self.stalls_over(100),
            "stalls_over_1s": self.stalls_over(1000),
        }


class LoopProbe:
    """``async with LoopProbe() as probe: ...``; read ``probe.stats`` after."""

    def __init__(self, interval: float = 0.005):
        self.interval = interval
        self.stats = LoopStats()
        self._task: asyncio.Task | None = None
        self._running = False
        self._started = 0.0

    async def _run(self) -> None:
        while self._running:
            before = time.perf_counter()
            await asyncio.sleep(self.interval)
            late = time.perf_counter() - before - self.interval
            self.stats.lags_s.append(max(0.0, late))

    async def __aenter__(self) -> "LoopProbe":
        # Collect garbage left by earlier tests now, so the collector does not
        # pause the loop in the middle of this measurement.
        gc.collect()
        self._running = True
        self._started = time.perf_counter()
        self._task = asyncio.create_task(self._run())
        # Let the probe take its first sample before the scenario starts.
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc) -> None:
        # One more turn so a stall at the very end is recorded.
        await asyncio.sleep(self.interval * 2)
        self._running = False
        self.stats.duration_s = time.perf_counter() - self._started
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
