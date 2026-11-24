"""Artifact routes: column-only access checks, sync handlers in the threadpool, no Zarr views."""

from __future__ import annotations

import asyncio
import inspect
import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from open_webui.models.chats import ChatAccessRow
from open_webui.routers import artifacts as artifacts_router
from open_webui.utils.artifacts import list_artifacts
from open_webui.utils.auth import get_verified_user

CHAT = "chat-r"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


class ArtifactRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.tmp.name) / "artifacts"
        root = self.artifacts / CHAT
        (root / "plots").mkdir(parents=True)
        (root / "plots" / "map.html").write_text("<html></html>")
        (root / "notes.csv").write_text("a,b\n")
        (root / "plots" / "map.png").write_bytes(PNG)
        (root / "old.zarrview.json").write_text('{"type": "zarr_view", "zarr": "x.zarr"}')
        self.chats = MagicMock()
        self.chats.is_live_share.return_value = False
        self.chats.get_chat_access_row.return_value = ChatAccessRow(
            id=CHAT, user_id="u1", organization_id="u1", visibility="private"
        )
        self.patches = [
            patch("open_webui.utils.artifacts.ARTIFACTS_DIR", self.artifacts),
            patch("open_webui.utils.organizations.Chats", self.chats),
        ]
        for p in self.patches:
            p.start()
        app = FastAPI()
        app.include_router(artifacts_router.router, prefix="/api/v1/chats")
        app.dependency_overrides[get_verified_user] = lambda: MagicMock(id="u1")
        for exc in (StarletteHTTPException, RequestValidationError):
            app.add_exception_handler(exc, artifacts_router.artifact_link_exception_handler)
        self.app = app
        self.client = TestClient(app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def url(self, rest: str) -> str:
        return f"/api/v1/chats/{CHAT}/artifacts{rest}"

    def test_access_checks_read_only_the_access_columns(self):
        self.assertEqual(self.client.get(self.url("/content?path=notes.csv")).status_code, 200)
        self.assertEqual(self.client.get(self.url("")).status_code, 200)
        self.chats.get_chat_access_row.assert_called_with(CHAT)
        self.chats.get_chat_by_id.assert_not_called()

    def test_another_users_private_chat_is_refused(self):
        self.chats.get_chat_access_row.return_value = ChatAccessRow(
            id=CHAT, user_id="someone-else", organization_id="someone-else", visibility="private"
        )
        with patch("open_webui.utils.organizations.is_member", return_value=False):
            res = self.client.get(self.url("/content?path=notes.csv"))
        self.assertEqual(res.status_code, 401)

    def test_a_dead_or_malformed_artifact_link_opened_in_a_tab_goes_to_the_app(self):
        tab = {"sec-fetch-dest": "document"}
        get = lambda path, headers: self.client.get(
            self.url(path), headers=headers, follow_redirects=False
        )
        for path, plain in (
            ("/content?path=gone.png", 404),
            ("/view/plots/gone.html", 404),
            ("/content?path=../escape", 400),
            ("/content", 422),
            ("/view/notes.csv", 415),
        ):
            res = get(path, tab)
            self.assertEqual(res.status_code, 303, path)
            self.assertEqual(res.headers["location"], artifacts_router.MISSING_ARTIFACT_REDIRECT)
            # Fetches and iframes keep the plain error.
            self.assertEqual(get(path, {"sec-fetch-dest": "iframe"}).status_code, plain, path)
        # Other routes are left alone.
        self.assertEqual(get("/archive?path=gone", tab).status_code, 404)
        # A chat the user cannot read looks the same as a missing one.
        self.chats.get_chat_access_row.return_value = None
        self.assertEqual(get("/content?path=notes.csv", tab).status_code, 303)

    def test_a_signed_out_tab_goes_to_sign_in_and_back(self):
        for detail in ("Not authenticated", "Invalid token"):

            def signed_out():
                raise HTTPException(status_code=401, detail=detail)

            self.app.dependency_overrides[get_verified_user] = signed_out
            get = lambda dest: self.client.get(
                # Encoded the way a copied link is.
                self.url("/content?path=plots%2Fmap.png"),
                headers={"sec-fetch-dest": dest},
                follow_redirects=False,
            )
            res = get("document")
            self.assertEqual(res.status_code, 303, detail)
            self.assertEqual(
                res.headers["location"],
                f"/auth?redirect=%2Fapi%2Fv1%2Fchats%2F{CHAT}%2Fartifacts%2Fcontent"
                "%3Fpath%3Dplots%252Fmap.png&sign-in-required=1",
            )
            self.assertEqual(get("iframe").status_code, 401)

    def test_handlers_that_await_nothing_are_plain_functions(self):
        for handler in (
            artifacts_router.get_artifact_content,
            artifacts_router.view_html_artifact,
            artifacts_router.get_artifact_archive,
            artifacts_router.get_artifact_size,
            artifacts_router.zarr_meta,
        ):
            self.assertFalse(inspect.iscoroutinefunction(handler), handler.__name__)

    def test_downloads_still_work(self):
        res = self.client.get(self.url("/content?path=notes.csv"))
        self.assertEqual(res.content, b"a,b\n")
        res = self.client.get(self.url("/content?path=plots"))
        self.assertEqual(res.headers["content-type"], "application/zip")
        res = self.client.get(self.url("/archive?path=plots&format=tar.gz"))
        self.assertEqual(res.status_code, 200)
        res = self.client.get(self.url("/view/plots/map.html"))
        self.assertEqual(res.status_code, 200)

    def test_folders_zip_in_a_child_process_without_symlinks(self):
        root = self.artifacts / CHAT
        (root / "plots" / "k.zarr").mkdir()
        (root / "plots" / "k.zarr" / ".zgroup").write_text("{}")
        (root / "plots" / "leak").symlink_to(root / "notes.csv")
        for url in ("/content?path=plots", "/archive?path=plots&format=zip"):
            res = self.client.get(self.url(url))
            self.assertEqual(res.status_code, 200)
            self.assertIn('filename="plots.zip"', res.headers["content-disposition"])
            with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
                self.assertEqual(
                    sorted(zf.namelist()),
                    ["plots/k.zarr/.zgroup", "plots/map.html", "plots/map.png"],
                )
                self.assertEqual(zf.read("plots/map.png"), PNG)
        # Text is deflated; data that does not shrink is stored as is.
        (root / "plots" / "table.csv").write_text("2024-01-01,1.5\n" * 10_000)
        (root / "plots" / "chunk").write_bytes(os.urandom(100_000))
        res = self.client.get(self.url("/content?path=plots"))
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            kinds = {i.filename: i.compress_type for i in zf.infolist()}
            self.assertEqual(kinds["plots/table.csv"], zipfile.ZIP_DEFLATED)
            self.assertEqual(kinds["plots/chunk"], zipfile.ZIP_STORED)
            self.assertIsNone(zf.testzip())
        res = self.client.get(self.url("/archive?path=missing&format=zip"))
        self.assertEqual(res.status_code, 404)

    def test_size_totals_a_folder(self):
        res = self.client.get(self.url("/size?path=plots"))
        self.assertEqual(res.json(), {"size": len("<html></html>") + len(PNG)})
        self.assertEqual(self.client.get(self.url("/size?path=nope")).status_code, 404)

    def test_size_is_null_for_a_folder_too_large_to_size(self):
        with patch("open_webui.utils.artifacts.shutil.which", return_value=None), patch(
            "open_webui.utils.artifacts.SIZE_WALK_MAX_FILES", 1
        ):
            res = self.client.get(self.url("/size?path=plots"))
        self.assertEqual(res.json(), {"size": None})

    def test_unchanged_file_answers_304_without_a_body(self):
        first = self.client.get(self.url("/content?path=plots/map.png"))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.content, PNG)
        self.assertEqual(first.headers["cache-control"], "private, no-cache")
        # A copied image link shows the image, sandboxed so an SVG's scripts can't run.
        self.assertTrue(first.headers["content-disposition"].startswith("inline"))
        self.assertEqual(first.headers["content-security-policy"], "sandbox")
        other = self.client.get(self.url("/content?path=notes.csv"))
        self.assertTrue(other.headers["content-disposition"].startswith("attachment"))
        etag = first.headers["etag"]
        again = self.client.get(
            self.url("/content?path=plots/map.png"), headers={"If-None-Match": etag}
        )
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.content, b"")
        self.assertEqual(again.headers["etag"], etag)
        self.assertEqual(again.headers["cache-control"], "private, no-cache")
        since = self.client.get(
            self.url("/content?path=plots/map.png"),
            headers={"If-Modified-Since": first.headers["last-modified"]},
        )
        self.assertEqual(since.status_code, 304)

    def test_a_rewritten_file_gets_a_new_etag(self):
        import os

        etag = self.client.get(self.url("/content?path=plots/map.png")).headers["etag"]
        target = self.artifacts / CHAT / "plots" / "map.png"
        target.write_bytes(PNG + b"new")
        os.utime(target, (target.stat().st_atime, target.stat().st_mtime + 5))
        res = self.client.get(
            self.url("/content?path=plots/map.png"), headers={"If-None-Match": etag}
        )
        self.assertEqual(res.status_code, 200)
        self.assertNotEqual(res.headers["etag"], etag)
        self.assertEqual(res.content, PNG + b"new")

    def test_archive_upload_extracts_off_the_loop(self):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = b"x,y\n"
            info = tarfile.TarInfo("out/result.csv")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        threads = []
        real_extract = artifacts_router.extract_sandbox_archive

        def extract(*args):
            import threading

            threads.append(threading.current_thread())
            return real_extract(*args)

        with patch.object(artifacts_router, "extract_sandbox_archive", extract), patch(
            "open_webui.utils.chat_realtime.schedule_artifacts"
        ):
            res = self.client.post(
                self.url("/archive"), files={"file": ("out.tar.gz", buf.getvalue())}
            )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["written"], ["out/result.csv"])
        self.assertEqual(len(threads), 1)
        self.assertNotEqual(threads[0].name, "MainThread")

    def test_zarr_view_routes_are_gone(self):
        self.assertEqual(self.client.get(self.url("/zarr/render?view=v.json")).status_code, 404)
        self.assertIn(self.client.post(self.url("/zarr/views"), json={}).status_code, (404, 405))

    def test_old_view_files_are_listed_as_plain_files(self):
        item = {i["path"]: i for i in list_artifacts(CHAT)}["old.zarrview.json"]
        self.assertEqual(item["kind"], "file")
        self.assertNotIn("missing_zarr", item)


if __name__ == "__main__":
    unittest.main()
