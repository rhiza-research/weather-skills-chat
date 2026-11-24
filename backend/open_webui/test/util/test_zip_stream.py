import io
import os
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from open_webui.utils import zip_stream


class Unseekable(io.RawIOBase):
    """Like the stdout pipe: zipfile cannot seek back to fix up headers."""

    def __init__(self):
        self.buf = bytearray()

    def writable(self):
        return True

    def write(self, b):
        self.buf += b
        return len(b)


def zip_bytes(pairs) -> zipfile.ZipFile:
    out = Unseekable()
    zip_stream.write_zip(out, pairs)
    return zipfile.ZipFile(io.BytesIO(bytes(out.buf)))


class ZipStreamTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.store = self.root / "store.zarr"
        (self.store / "b").mkdir(parents=True)
        (self.store / "zarr.json").write_text('{"a": 1}' * 100)
        (self.store / "b" / "0").write_bytes(os.urandom(5000))
        (self.store / "b" / "1").write_bytes(os.urandom(3000))
        (self.store / "link").symlink_to(self.store / "zarr.json")
        zip_stream._running_zips = 1
        self.addCleanup(setattr, zip_stream, "_running_zips", 1)

    def test_a_folder_zips_in_order_without_symlinks(self):
        with patch.object(zip_stream, "READ_AHEAD_MAX_FILE_BYTES", 4000):
            zf = zip_bytes([("store.zarr", str(self.store))])
        self.assertIsNone(zf.testzip())
        self.assertEqual(
            zf.namelist(), ["store.zarr/zarr.json", "store.zarr/b/0", "store.zarr/b/1"]
        )
        # b/0 is over the read-ahead limit, so the writer read it itself.
        self.assertEqual(
            zf.read("store.zarr/b/0"), (self.store / "b" / "0").read_bytes()
        )
        kinds = {i.filename: i.compress_type for i in zf.infolist()}
        self.assertEqual(kinds["store.zarr/zarr.json"], zipfile.ZIP_DEFLATED)
        self.assertEqual(kinds["store.zarr/b/1"], zipfile.ZIP_STORED)

    def test_reads_in_flight_stay_within_this_zips_share(self):
        for i in range(20):
            (self.store / "b" / f"x{i}").write_bytes(b"y" * 10)
        active = peak = 0
        lock = threading.Lock()
        read = zip_stream._read

        def slow_read(path):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return read(path)

        zip_stream._running_zips = 2
        with (
            patch.object(zip_stream, "READ_THREADS", 8),
            patch.object(zip_stream, "_read", slow_read),
        ):
            zf = zip_bytes([("store.zarr", str(self.store))])
        self.assertIsNone(zf.testzip())
        self.assertEqual(peak, 4)

    def test_bytes_held_stay_within_the_budget(self):
        entries = [
            (f"f{i}", f"p{i}", os.stat_result((0o100644, 0, 0, 0, 0, 0, 10, 0, 0, 0)))
            for i in range(6)
        ]
        submitted = []

        class Pool:
            def submit(self, fn, path):
                submitted.append(path)
                future = unittest.mock.Mock()
                future.result.return_value = b"x" * 10
                return future

        with patch.object(zip_stream, "READ_AHEAD_BYTES", 25):
            reads = zip_stream._read_ahead(iter(entries), Pool())
            # Two 10-byte files fit in 25 bytes; the third waits for the first.
            next(reads)
            self.assertEqual(submitted, ["p0", "p1"])
            next(reads)
            self.assertEqual(submitted, ["p0", "p1", "p2"])

    def test_zip64_offsets_through_a_pipe(self):
        with patch.object(zipfile, "ZIP64_LIMIT", 2000):
            zf = zip_bytes([("store.zarr", str(self.store))])
            self.assertIsNone(zf.testzip())
            self.assertEqual(len(zf.namelist()), 3)

    def test_dates_before_1980_are_clamped(self):
        os.utime(self.store / "zarr.json", (0, 0))
        zf = zip_bytes([("zarr.json", str(self.store / "zarr.json"))])
        self.assertEqual(zf.getinfo("zarr.json").date_time, (1980, 1, 1, 0, 0, 0))

    def test_running_zips_follow_stdin_lines(self):
        zip_stream._follow_running_zips(["3\n", "oops\n", "0\n"])
        self.assertEqual(zip_stream._running_zips, 1)
        zip_stream._follow_running_zips(["4\n"])
        self.assertEqual(zip_stream._running_zips, 4)


if __name__ == "__main__":
    unittest.main()
