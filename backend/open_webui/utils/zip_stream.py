"""Write a zip of files and folders to stdout, for artifact downloads.

Run as its own low-priority process (``python -I zip_stream.py ARCNAME PATH ...``)
so zipping never holds the chat server's GIL or memory. Standard library only:
``-I`` keeps the app's packages off sys.path.
"""

import os
import sys
import zipfile
import zlib

# File data streams through in small buffers; what grows is the zip's index,
# about 500 bytes per file, so this allows roughly 1.5 million files.
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
SAMPLE_BYTES = 64 * 1024


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


def _compress_type(path: str) -> int:
    """Deflate only data that shrinks. Zarr chunks, PNGs and NetCDF are usually
    compressed already; deflating them costs a core for no gain."""
    with open(path, "rb") as f:
        head = f.read(SAMPLE_BYTES)
    if head and len(zlib.compress(head, 1)) < 0.9 * len(head):
        return zipfile.ZIP_DEFLATED
    return zipfile.ZIP_STORED


def _add(zf: zipfile.ZipFile, path: str, arcname: str) -> None:
    zf.write(path, arcname=arcname, compress_type=_compress_type(path), compresslevel=1)


def write_zip(out, pairs: list[tuple[str, str]]) -> None:
    """Zip each (arcname, path). Folders are walked; symlinks are skipped."""
    with zipfile.ZipFile(out, mode="w") as zf:
        for arcname, path in pairs:
            if os.path.isfile(path) and not os.path.islink(path):
                _add(zf, path, arcname)
                continue
            for dirpath, dirnames, filenames in os.walk(path):
                dirnames.sort()
                for name in sorted(filenames):
                    child = os.path.join(dirpath, name)
                    if os.path.islink(child) or not os.path.isfile(child):
                        continue
                    rel = os.path.relpath(child, path).replace(os.sep, "/")
                    _add(zf, child, f"{arcname}/{rel}")


if __name__ == "__main__":
    _limit_self()
    args = sys.argv[1:]
    write_zip(sys.stdout.buffer, list(zip(args[::2], args[1::2])))
    sys.stdout.buffer.flush()
