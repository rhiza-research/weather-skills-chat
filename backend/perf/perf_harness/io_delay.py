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
- JuiceFS reads: a first read of large files in staging's artifact store ran
  at 60-256 MB/s (about 5 ms per MB); a file a skill just wrote on a runner is
  a first read on the chat server.

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
FS_READ_S_PER_MB = 0.005


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


class _SlowReader:
    """A file object whose reads take ``s_per_mb`` per megabyte read."""

    def __init__(self, f, s_per_mb: float):
        self._f = f
        self._s_per_mb = s_per_mb

    def _charge(self, n: int) -> None:
        if n:
            time.sleep(n / 1_000_000 * self._s_per_mb)

    def read(self, *args):
        data = self._f.read(*args)
        self._charge(len(data))
        return data

    def readinto(self, buffer):
        n = self._f.readinto(buffer)
        self._charge(n or 0)
        return n

    def readline(self, *args):
        data = self._f.readline(*args)
        self._charge(len(data))
        return data

    def __iter__(self):
        for line in self._f:
            self._charge(len(line))
            yield line

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return self._f.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._f, name)


@contextlib.contextmanager
def fs_delay(
    roots: Iterable[os.PathLike | str],
    metadata_s: float = FS_METADATA_S,
    open_s: float = FS_OPEN_S,
    read_s_per_mb: float = FS_READ_S_PER_MB,
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
            # shutil.rmtree and friends work relative to an open directory
            # (dir_fd, or scandir on a descriptor) and never pass the full
            # path. Inside the window those are sandbox walks, so count them.
            if slow(path) or kwargs.get("dir_fd") is not None or (
                isinstance(path, int) and fn.__name__ == "scandir"
            ):
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
    originals.append((os, "open", os.open))
    os.open = wrap(os.open, open_s)
    real_open = builtins.open

    def slow_open(file, mode="r", *args, **kwargs):
        if not slow(file):
            return real_open(file, mode, *args, **kwargs)
        time.sleep(open_s)
        f = real_open(file, mode, *args, **kwargs)
        if "r" in mode and "+" not in mode:
            return _SlowReader(f, read_s_per_mb)
        return f

    for module, name in ((builtins, "open"), (io, "open"), (tarfile, "bltn_open")):
        originals.append((module, name, getattr(module, name)))
        setattr(module, name, slow_open)
    try:
        yield
    finally:
        for module, name, fn in reversed(originals):
            setattr(module, name, fn)
