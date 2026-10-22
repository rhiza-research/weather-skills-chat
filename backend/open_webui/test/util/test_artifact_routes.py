"""Artifact routes: column-only access checks, sync handlers in the threadpool, no Zarr views."""

from __future__ import annotations

import asyncio
import inspect
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_webui.models.chats import ChatAccessRow
from open_webui.routers import artifacts as artifacts_router
from open_webui.utils.artifacts import list_artifacts
from open_webui.utils.auth import get_verified_user

CHAT = "chat-r"


class ArtifactRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.tmp.name) / "artifacts"
        root = self.artifacts / CHAT
        (root / "plots").mkdir(parents=True)
        (root / "plots" / "map.html").write_text("<html></html>")
        (root / "notes.csv").write_text("a,b\n")
        (root / "old.zarrview.json").write_text('{"type": "zarr_view", "zarr": "x.zarr"}')
        self.chats = MagicMock()
        self.chats.get_chat_access_row.return_value = ChatAccessRow(
            id=CHAT, user_id="u1", organization_id="u1", visibility="private"
        )
        self.patches = [
            patch("open_webui.utils.artifacts.ARTIFACTS_DIR", self.artifacts),
            patch.object(artifacts_router, "Chats", self.chats),
        ]
        for p in self.patches:
            p.start()
        app = FastAPI()
        app.include_router(artifacts_router.router, prefix="/api/v1/chats")
        app.dependency_overrides[get_verified_user] = lambda: MagicMock(id="u1")
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

    def test_handlers_that_await_nothing_are_plain_functions(self):
        for handler in (
            artifacts_router.get_artifact_content,
            artifacts_router.view_html_artifact,
            artifacts_router.get_artifact_archive,
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
