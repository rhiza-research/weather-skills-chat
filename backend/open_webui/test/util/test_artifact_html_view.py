"""HTML artifacts are served inline only behind a CSP sandbox."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_webui.routers import artifacts as artifacts_router
from open_webui.utils.artifacts import list_artifacts
from open_webui.utils.auth import get_verified_user

PAGE = b"<html><body><div id='plot'></div></body></html>"


class HtmlViewRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.tmp.name) / "artifacts"
        root = self.artifacts / "chat-1"
        (root / "plots").mkdir(parents=True)
        (root / "plots" / "sst 2017.html").write_bytes(PAGE)
        (root / "data.csv").write_bytes(b"a,b\n")
        self.patches = [
            patch("open_webui.utils.artifacts.ARTIFACTS_DIR", self.artifacts),
            patch.object(artifacts_router, "Chats", MagicMock()),
            patch.object(artifacts_router, "can_read_chat", return_value=True),
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

    def test_html_is_served_inline_inside_a_csp_sandbox(self):
        res = self.client.get("/api/v1/chats/chat-1/artifacts/view/plots/sst%202017.html")
        self.assertEqual(res.status_code, 200)
        # The file as written, then the read-only script reporting its size.
        self.assertTrue(res.content.startswith(PAGE))
        self.assertIn(b"weather-skills:figure-size", res.content[len(PAGE):])
        self.assertTrue(res.headers["content-type"].startswith("text/html"))
        self.assertNotIn("content-disposition", res.headers)
        csp = res.headers["content-security-policy"]
        self.assertTrue(csp.startswith("sandbox"))
        self.assertIn("allow-scripts", csp)
        self.assertNotIn("allow-same-origin", csp)
        self.assertEqual(res.headers["x-content-type-options"], "nosniff")
        self.assertEqual(res.headers["referrer-policy"], "no-referrer")

    def test_only_html_can_be_viewed(self):
        res = self.client.get("/api/v1/chats/chat-1/artifacts/view/data.csv")
        self.assertEqual(res.status_code, 415)

    def test_missing_and_escaping_paths(self):
        self.assertEqual(
            self.client.get("/api/v1/chats/chat-1/artifacts/view/nope.html").status_code, 404
        )
        res = self.client.get("/api/v1/chats/chat-1/artifacts/view/..%2F..%2Fsecret.html")
        self.assertIn(res.status_code, (400, 404))

    def test_a_chat_the_user_cannot_read_is_refused(self):
        with patch.object(artifacts_router, "can_read_chat", return_value=False):
            res = self.client.get("/api/v1/chats/chat-1/artifacts/view/plots/sst%202017.html")
        self.assertEqual(res.status_code, 401)

    def test_listing_marks_html_files(self):
        kinds = {item["path"]: item["kind"] for item in list_artifacts("chat-1")}
        self.assertEqual(kinds["plots/sst 2017.html"], "html")
        self.assertEqual(kinds["data.csv"], "file")

    def test_listing_reports_when_a_file_was_rewritten(self):
        import os

        target = self.artifacts / "chat-1" / "plots" / "sst 2017.html"
        before = {i["path"]: i for i in list_artifacts("chat-1")}["plots/sst 2017.html"]
        self.assertIsInstance(before["modified"], int)
        os.utime(target, (target.stat().st_atime, target.stat().st_mtime + 5))
        after = {i["path"]: i for i in list_artifacts("chat-1")}["plots/sst 2017.html"]
        self.assertGreater(after["modified"], before["modified"])
        folder = {i["path"]: i for i in list_artifacts("chat-1")}["plots"]
        self.assertIsNone(folder["modified"])
