"""Greppable send-path timings: `chat-timing`.

Staging JuiceFS/Postgres latency is the point of these logs. Keep fields
numeric (counts, bytes, seconds) — never payload/secret contents.
"""

import logging
import time
from typing import Any

log = logging.getLogger(__name__)

PREFIX = "chat-timing"


def log_timing(stage: str, seconds: float, **fields: Any) -> None:
    extra = " ".join(
        f"{key}={value}" for key, value in fields.items() if value is not None
    )
    suffix = f" {extra}" if extra else ""
    log.info("%s %s %.3fs%s", PREFIX, stage, seconds, suffix)


class StageClock:
    def __init__(self, label: str, **fields: Any):
        self.label = label
        self.fields = {k: v for k, v in fields.items() if v is not None}
        self.t0 = time.perf_counter()
        self.last = self.t0
        self.parts: list[tuple[str, float]] = []

    def elapsed(self) -> float:
        return time.perf_counter() - self.t0

    def mark(self, name: str, **fields: Any) -> float:
        now = time.perf_counter()
        dt = now - self.last
        self.last = now
        self.parts.append((name, dt))
        log_timing(f"{self.label}.{name}", dt, **self.fields, **fields)
        return dt

    def done(self, **fields: Any) -> float:
        total = self.elapsed()
        summary = " ".join(f"{name}={dt:.3f}s" for name, dt in self.parts)
        extra = " ".join(
            f"{key}={value}"
            for key, value in {**self.fields, **fields}.items()
            if value is not None
        )
        bits = " ".join(p for p in (summary, extra) if p)
        suffix = f" {bits}" if bits else ""
        log.info("%s %s.total %.3fs%s", PREFIX, self.label, total, suffix)
        return total
