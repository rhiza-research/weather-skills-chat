from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
import zipfile
import zlib
import struct
from pathlib import Path
from unittest.mock import patch

from open_webui.utils.artifacts import (
    SANDBOX_FILE_MODE,
    SANDBOX_OWNER_UID,
    copy_sandbox,
    copy_upload_into_chat_sandbox,
    create_folder,
    extract_sandbox_archive,
    normalize_sandbox_relpath,
    pack_sandbox_archive,
    pack_sandbox_zip,
    write_bytes,
    write_json,
)


class NormalizePathTest(unittest.TestCase):
    def test_strips_slashes(self):
        self.assertEqual(normalize_sandbox_relpath("/plots/a.png"), "plots/a.png")

    def test_rejects_parent_segments(self):
        with self.assertRaises(ValueError):
            normalize_sandbox_relpath("../secret")
        with self.assertRaises(ValueError):
            normalize_sandbox_relpath("foo/../../secret")


class CreateFolderTest(unittest.TestCase):
    def test_new_subfolders_are_group_writable(self):
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                result = create_folder("chat-1", "plots/weekly")
                weekly = artifacts / "chat-1" / "plots" / "weekly"
                plots = weekly.parent
                self.assertTrue(result["created"])
                self.assertTrue(weekly.is_dir())
                for path in (weekly, plots):
                    mode = stat.S_IMODE(path.stat().st_mode)
                    self.assertTrue(mode & stat.S_IWGRP, f"{path} not group-writable: {oct(mode)}")
                    self.assertTrue(mode & stat.S_ISGID, f"{path} missing setgid: {oct(mode)}")


class CopySandboxTest(unittest.TestCase):
    def test_copies_visible_files_and_zarr_dotfiles_not_root_dotdirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                src = artifacts / "src"
                (src / "plots").mkdir(parents=True)
                (src / "plots" / "map.png").write_bytes(b"png")
                (src / "data.zarr").mkdir()
                (src / "data.zarr" / ".zgroup").write_text("{}")
                (src / ".local").mkdir()
                (src / ".local" / "secret").write_text("nope")
                copy_sandbox("src", "dest")
                dest = artifacts / "dest"
                self.assertEqual((dest / "plots" / "map.png").read_bytes(), b"png")
                self.assertEqual((dest / "data.zarr" / ".zgroup").read_text(), "{}")
                self.assertFalse((dest / ".local").exists())


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

    def test_extract_strips_provenance_from_zarr_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-1"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                (artifacts / chat_id / "intermediate_results").mkdir(parents=True)
                import io

                zattrs = {
                    "weather_skills_history": [{"skill": "plot"}],
                    "rhiza_history_alpha": [{"skill": "reduce"}],
                    "keep": 1,
                }
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                    info = tarfile.TarInfo(name="out/demo.zarr/.zattrs")
                    payload = json_bytes(zattrs)
                    info.size = len(payload)
                    tar.addfile(info, io.BytesIO(payload))
                extract_sandbox_archive(chat_id, buf.getvalue())
                saved = json.loads(
                    (artifacts / chat_id / "out" / "demo.zarr" / ".zattrs").read_text()
                )
                self.assertNotIn("weather_skills_history", saved)
                self.assertNotIn("rhiza_history_alpha", saved)
                self.assertEqual(saved["keep"], 1)

    def test_extract_strips_provenance_text_chunks_from_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-1"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                (artifacts / chat_id / "intermediate_results").mkdir(parents=True)
                import io
                from open_webui.utils.artifacts import read_png_text_chunks

                png = minimal_png_with_text(
                    {
                        "weather_skills_history": '[{"skill":"plot"}]',
                        "note": "keep me",
                    }
                )
                buf = io.BytesIO()
                with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                    info = tarfile.TarInfo(name="plots/out.png")
                    info.size = len(png)
                    tar.addfile(info, io.BytesIO(png))
                extract_sandbox_archive(chat_id, buf.getvalue())
                saved_path = artifacts / chat_id / "plots" / "out.png"
                texts = read_png_text_chunks(saved_path)
                self.assertNotIn("weather_skills_history", texts)
                self.assertEqual(texts.get("note"), "keep me")

    def test_missing_input_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                (artifacts / "c" / "intermediate_results").mkdir(parents=True)
                with self.assertRaises(FileNotFoundError):
                    pack_sandbox_archive("c", ["missing.csv"])

    def test_zip_packs_file_and_zarr_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-zip"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                root = artifacts / chat_id
                (root / "intermediate_results").mkdir(parents=True)
                (root / "notes.csv").write_text("a,b\n1,2\n")
                zarr = root / "kenya.zarr"
                zarr.mkdir()
                (zarr / ".zgroup").write_text('{"zarr_format":2}')

                data = pack_sandbox_zip(chat_id, ["notes.csv", "kenya.zarr"])
                with zipfile.ZipFile(__import__("io").BytesIO(data)) as zf:
                    members = set(zf.namelist())
                self.assertIn("notes.csv", members)
                self.assertIn("kenya.zarr/.zgroup", members)


class CopyUploadIntoSandboxTest(unittest.TestCase):
    def test_writes_basename_at_sandbox_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                rel = copy_upload_into_chat_sandbox(
                    "chat-up", "../secret/notes.csv", b"a,b\n"
                )
                self.assertEqual(rel, "notes.csv")
                dest = artifacts / "chat-up" / "notes.csv"
                self.assertTrue(dest.is_file())
                self.assertEqual(dest.read_bytes(), b"a,b\n")


class SandboxWriterOwnTest(unittest.TestCase):
    def test_write_bytes_is_group_writable(self):
        import stat

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts):
                dest = write_bytes("chat-1", "notes.csv", b"a,b\n")
                mode = stat.S_IMODE(dest.stat().st_mode)
                self.assertTrue(mode & stat.S_IWGRP, f"not group-writable: {oct(mode)}")
                self.assertEqual(mode, SANDBOX_FILE_MODE)

    def test_writers_chown_to_runner_uid(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            with patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts), patch(
                "open_webui.utils.artifacts.os.chown"
            ) as chown:
                write_bytes("chat-1", "notes.csv", b"a")
                write_json("chat-1", "view.zarrview.json", {"ok": True})
                create_folder("chat-1", "plots/weekly")
        owned = {Path(call.args[0]) for call in chown.call_args_list}
        uids = {call.args[1] for call in chown.call_args_list}
        self.assertTrue(any(path.name == "notes.csv" for path in owned))
        self.assertTrue(any(path.name == "view.zarrview.json" for path in owned))
        self.assertTrue(any(path.name == "weekly" for path in owned))
        self.assertEqual(uids, {SANDBOX_OWNER_UID})


def json_bytes(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def minimal_png_with_text(texts: dict[str, str]) -> bytes:
    png_sig = b"\x89PNG\r\n\x1a\n"

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind)
        crc = zlib.crc32(data, crc) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", crc)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\x00\x00\x00")
    out = bytearray(png_sig)
    out.extend(chunk(b"IHDR", ihdr))
    for key, value in texts.items():
        out.extend(chunk(b"tEXt", key.encode("latin-1") + b"\x00" + value.encode("latin-1")))
    out.extend(chunk(b"IDAT", idat))
    out.extend(chunk(b"IEND", b""))
    return bytes(out)


class ContentDownloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_zarr_store_downloads_as_zip(self):
        import io
        from unittest.mock import MagicMock

        from open_webui.routers.artifacts import get_artifact_content

        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-zarr"
            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.routers.artifacts._readable"),
            ):
                root = artifacts / chat_id
                (root / "intermediate_results").mkdir(parents=True)
                zarr = root / "gambia_imerg_last_week.zarr"
                zarr.mkdir()
                (zarr / ".zgroup").write_text("{}")
                (zarr / "precip").mkdir()
                (zarr / "precip" / ".zarray").write_text("{}")

                resp = await get_artifact_content(
                    chat_id, "gambia_imerg_last_week.zarr", user=MagicMock()
                )
                self.assertEqual(resp.media_type, "application/zip")
                self.assertIn(
                    "gambia_imerg_last_week.zarr.zip",
                    resp.headers["content-disposition"],
                )
                chunks = [chunk async for chunk in resp.body_iterator]
                data = b"".join(chunks)
                with zipfile.ZipFile(io.BytesIO(data)) as zf:
                    members = set(zf.namelist())
                self.assertIn("gambia_imerg_last_week.zarr/.zgroup", members)
                self.assertIn("gambia_imerg_last_week.zarr/precip/.zarray", members)


if __name__ == "__main__":
    unittest.main()
