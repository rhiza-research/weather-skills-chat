"""Write a zip of files and folders to stdout, for artifact downloads.

Run as its own low-priority process (``python -I zip_stream.py ARCNAME PATH ...``)
so zipping never holds the chat server's GIL or memory. Standard library only:
``-I`` keeps the app's packages off sys.path.

Each line on stdin is the number of zips running now; this zip uses its share
of READ_THREADS and READ_AHEAD_BYTES. Run with MALLOC_ARENA_MAX=2: otherwise
each reader thread can reserve its own 64 MB malloc arena and pass the
address-space cap.
"""

import collections
import os
import stat
import sys
import threading
import time
import zipfile
import zlib
from concurrent.futures import ThreadPoolExecutor

# File data streams through in small buffers; what grows is the zip's index,
# about 500 bytes per file, so this allows roughly 1.5 million files.
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
SAMPLE_BYTES = 64 * 1024
# Reading a file from JuiceFS's object store takes about 100 ms, so reads run
# in parallel: 32 at once read about 165 MB/s on staging, one at a time 4 MB/s.
# Shared by all running zips, so the JuiceFS client's CPU use stays bounded.
READ_THREADS = 32
# Bytes held by reads not yet written, shared like the threads. Throughput
# times latency is about 30 MB, so this does not slow reads.
READ_AHEAD_BYTES = 64 * 1024 * 1024
# Larger files are read by the writer in small buffers, not held whole.
READ_AHEAD_MAX_FILE_BYTES = 16 * 1024 * 1024
THREAD_STACK_BYTES = 256 * 1024

_running_zips = 1


def _limit_self() -> None:
    os.nice(19)
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
    except (ImportError, ValueError, OSError):
        pass  # Not supported on this platform (macOS dev); nice still applies.
    try:
        # Under memory pressure the kernel kills this process, not the chat server.
        with open("/proc/self/oom_score_adj", "w") as f:
            f.write("1000")
    except OSError:
        pass  # Not Linux.


def _follow_running_zips(lines) -> None:
    global _running_zips
    for line in lines:
        try:
            _running_zips = max(1, int(line))
        except ValueError:
            pass


def _compress_type(head: bytes) -> int:
    """Deflate only data that shrinks. Zarr chunks, PNGs and NetCDF are usually
    compressed already; deflating them costs a core for no gain."""
    if head and len(zlib.compress(head, 1)) < 0.9 * len(head):
        return zipfile.ZIP_DEFLATED
    return zipfile.ZIP_STORED


def _entries(pairs: list[tuple[str, str]]):
    """(arcname, path, lstat) of each regular file. Folders are walked in
    sorted order; symlinks are skipped."""
    for arcname, path in pairs:
        st = os.lstat(path)
        if stat.S_ISREG(st.st_mode):
            yield arcname, path, st
            continue
        if not stat.S_ISDIR(st.st_mode):
            continue
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames.sort()
            for name in sorted(filenames):
                child = os.path.join(dirpath, name)
                st = os.lstat(child)
                if stat.S_ISREG(st.st_mode):
                    rel = os.path.relpath(child, path).replace(os.sep, "/")
                    yield f"{arcname}/{rel}", child, st


def _read(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _read_ahead(entries, pool: ThreadPoolExecutor):
    """Yield (arcname, path, lstat, data) in order. data is None for a file
    too large to hold, which the writer reads itself."""
    window = collections.deque()
    held = 0

    def full(size: int) -> bool:
        share = _running_zips
        return (
            len(window) >= max(1, READ_THREADS // share)
            or held + size > READ_AHEAD_BYTES // share
        )

    for arcname, path, st in entries:
        large = st.st_size > READ_AHEAD_MAX_FILE_BYTES
        while window and (large or full(st.st_size)):
            entry, future = window.popleft()
            held -= entry[2].st_size
            yield *entry, future.result()
        if large:
            yield arcname, path, st, None
            continue
        window.append(((arcname, path, st), pool.submit(_read, path)))
        held += st.st_size
    while window:
        entry, future = window.popleft()
        yield *entry, future.result()


def _zip_info(arcname: str, st: os.stat_result) -> zipfile.ZipInfo:
    # Zip dates start in 1980, as zipfile's strict_timestamps=False does.
    date_time = max(time.localtime(st.st_mtime)[:6], (1980, 1, 1, 0, 0, 0))
    info = zipfile.ZipInfo(arcname, date_time)
    info.external_attr = (st.st_mode & 0xFFFF) << 16
    return info


def write_zip(out, pairs: list[tuple[str, str]]) -> None:
    """Zip each (arcname, path). Folders are walked; symlinks are skipped."""
    with (
        ThreadPoolExecutor(READ_THREADS) as pool,
        zipfile.ZipFile(out, mode="w") as zf,
    ):
        for arcname, path, st, data in _read_ahead(_entries(pairs), pool):
            if data is None:
                with open(path, "rb") as f:
                    head = f.read(SAMPLE_BYTES)
                zf.write(path, arcname, _compress_type(head), compresslevel=1)
                continue
            zf.writestr(
                _zip_info(arcname, st),
                data,
                compress_type=_compress_type(data[:SAMPLE_BYTES]),
                compresslevel=1,
            )


if __name__ == "__main__":
    _limit_self()
    threading.stack_size(THREAD_STACK_BYTES)
    threading.Thread(
        target=_follow_running_zips, args=(sys.stdin,), daemon=True
    ).start()
    args = sys.argv[1:]
    write_zip(sys.stdout.buffer, list(zip(args[::2], args[1::2])))
    sys.stdout.buffer.flush()
