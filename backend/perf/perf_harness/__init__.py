"""Measure event-loop blocking under production-like I/O latency.

See backend/perf/README.md.
"""

from .io_delay import DB_STATEMENT_S, FS_METADATA_S, FS_OPEN_S, db_delay, fs_delay
from .probe import LoopProbe, LoopStats
from .report import check_budget, record

__all__ = [
    "DB_STATEMENT_S",
    "FS_METADATA_S",
    "FS_OPEN_S",
    "LoopProbe",
    "LoopStats",
    "check_budget",
    "db_delay",
    "fs_delay",
    "record",
]
