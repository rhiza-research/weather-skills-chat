"""Give local test I/O the latency it has in production.

Tests run on an in-process SQLite file and local disk, where a query or a stat
takes microseconds, so blocking the event loop with one costs nothing. In
production each is a network round trip. These helpers put a real
``time.sleep`` inside the synchronous call: on the event loop it stalls the
loop for that long, on a worker thread only that thread waits. That is the
difference the event-loop fixes make.

Defaults are calibrated from production chat-timing logs (2026-10-21):

- DB: small lookups such as ``db.Models.get_model_by_id`` take 4-5 ms in prod
  (882 calls, 4.6 ms mean). SQLite and ORM overhead is already paid locally,
  so each statement sleeps ``DB_STATEMENT_S``.
- JuiceFS: ``juicefs.chat_sandbox`` does about 26 metadata operations in
  9.4 ms on average, so ~0.35 ms each. Opening a file also fetches its first
  data from object storage. With these values, listing a 753-entry sandbox
  with provenance takes about as long as the 2.1 s it took in prod.

Langfuse exports are modeled in test_langfuse_flush.py, where the measurement
is described.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import os
import tarfile
import time
from typing import Iterable

DB_STATEMENT_S = 0.004
FS_METADATA_S = 0.00035
FS_OPEN_S = 0.001


@contextlib.contextmanager
def db_delay(seconds: float = DB_STATEMENT_S):
    """Every SQL statement on any SQLAlchemy engine waits ``seconds`` first."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    def before_execute(conn, cursor, statement, params, context, executemany):
        time.sleep(seconds)

    event.listen(Engine, "before_cursor_execute", before_execute)
    try:
        yield
    finally:
        event.remove(Engine, "before_cursor_execute", before_execute)


# os functions that take a path. pathlib, os.path, shutil and tarfile all
# reach the filesystem through these and open().
_METADATA_CALLS = [
    "stat",
    "lstat",
    "listdir",
    "scandir",
    "mkdir",
    "chown",
    "chmod",
    "utime",
    "unlink",
    "remove",
    "rmdir",
    "rename",
    "replace",
]


@contextlib.contextmanager
def fs_delay(
    roots: Iterable[os.PathLike | str],
    metadata_s: float = FS_METADATA_S,
    open_s: float = FS_OPEN_S,
):
    """Filesystem calls on paths under ``roots`` behave like JuiceFS.

    Only those paths are slowed, so pytest, imports and the SQLite file keep
    local-disk speed.
    """
    prefixes = tuple(str(os.path.realpath(root)) for root in roots) + tuple(
        str(root) for root in roots
    )

    def slow(path) -> bool:
        if isinstance(path, int):
            return False
        try:
            text = os.fspath(path)
        except TypeError:
            return False
        if isinstance(text, bytes):
            text = text.decode(errors="ignore")
        return text.startswith(prefixes)

    def wrap(fn, cost):
        def delayed(path, *args, **kwargs):
            if slow(path):
                time.sleep(cost)
            return fn(path, *args, **kwargs)

        delayed.__wrapped__ = fn
        return delayed

    originals = []
    for name in _METADATA_CALLS:
        fn = getattr(os, name, None)
        if fn is not None:
            originals.append((os, name, fn))
            setattr(os, name, wrap(fn, metadata_s))
    real_open = builtins.open
    slow_open = wrap(real_open, open_s)
    for module, name in ((builtins, "open"), (io, "open"), (tarfile, "bltn_open")):
        originals.append((module, name, getattr(module, name)))
        setattr(module, name, slow_open)
    try:
        yield
    finally:
        for module, name, fn in reversed(originals):
            setattr(module, name, fn)
