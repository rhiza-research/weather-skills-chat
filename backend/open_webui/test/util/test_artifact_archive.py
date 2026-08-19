from __future__ import annotations

import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_webui.utils.artifacts import (
    extract_sandbox_archive,
    normalize_sandbox_relpath,
    pack_sandbox_archive,
)


class NormalizePathTest(unittest.TestCase):
    def test_strips_slashes(self):
        self.assertEqual(normalize_sandbox_relpath("/plots/a.png"), "plots/a.png")

    def test_rejects_parent_segments(self):
        with self.assertRaises(ValueError):
            normalize_sandbox_relpath("../secret")
        with self.assertRaises(ValueError):
            normalize_sandbox_relpath("foo/../../secret")


class ArchiveRoundTripTest(unittest.TestCase):
    def test_packs_file_and_zarr_tree_including_dotfiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-1"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                root = artifacts / chat_id
                (root / "intermediate_results").mkdir(parents=True)
                (root / "notes.csv").write_text("a,b\n1,2\n")
                zarr = root / "kenya.zarr"
                zarr.mkdir()
                (zarr / ".zgroup").write_text('{"zarr_format":2}')
                (zarr / "precip").mkdir()
                (zarr / "precip" / ".zarray").write_text("{}")
                (zarr / "precip" / "0").write_bytes(b"chunk")

                data = pack_sandbox_archive(
                    chat_id, ["notes.csv", "kenya.zarr"]
                )
                names = tarfile.open(fileobj=__import__("io").BytesIO(data), mode="r:gz")
                members = set(names.getnames())
                names.close()
                self.assertIn("notes.csv", members)
                self.assertIn("kenya.zarr/.zgroup", members)
                self.assertIn("kenya.zarr/precip/.zarray", members)
                self.assertIn("kenya.zarr/precip/0", members)

    def test_extract_writes_into_sandbox_and_blocks_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-1"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                (artifacts / chat_id / "intermediate_results").mkdir(parents=True)

                import io

                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                    info = tarfile.TarInfo(name="out/result.txt")
                    payload = b"hello"
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))
                    evil = tarfile.TarInfo(name="../pwned.txt")
                    payload_evil = b"no"
                    evil.size = len(payload_evil)
                    tar.addfile(evil, io.BytesIO(payload_evil))
                raw = buf.getvalue()

                with self.assertRaises(ValueError):
                    extract_sandbox_archive(chat_id, raw)

                # valid-only archive
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                    info = tarfile.TarInfo(name="out/result.txt")
                    payload = b"hello"
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))
                written = extract_sandbox_archive(chat_id, buf.getvalue())
                self.assertEqual(written, ["out/result.txt"])
                dest = artifacts / chat_id / "out" / "result.txt"
                self.assertEqual(dest.read_bytes(), b"hello")

    def test_missing_input_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                (artifacts / "c" / "intermediate_results").mkdir(parents=True)
                with self.assertRaises(FileNotFoundError):
                    pack_sandbox_archive("c", ["missing.csv"])


if __name__ == "__main__":
    unittest.main()
