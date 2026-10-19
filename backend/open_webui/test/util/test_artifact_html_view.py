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

    def test_unchanged_page_answers_304_without_a_body(self):
        url = "/api/v1/chats/chat-1/artifacts/view/plots/sst%202017.html"
        first = self.client.get(url)
        etag = first.headers["etag"]
        self.assertTrue(etag.startswith('W/"'))
        self.assertIn("last-modified", first.headers)
        again = self.client.get(url, headers={"If-None-Match": etag})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.content, b"")
        self.assertEqual(again.headers["etag"], etag)
        # Still sandboxed, so a 304 never leaves the page without its CSP.
        self.assertIn("sandbox", again.headers["content-security-policy"])
        since = self.client.get(url, headers={"If-Modified-Since": first.headers["last-modified"]})
        self.assertEqual(since.status_code, 304)

    def test_a_rewritten_page_gets_a_new_etag(self):
        import os

        url = "/api/v1/chats/chat-1/artifacts/view/plots/sst%202017.html"
        etag = self.client.get(url).headers["etag"]
        target = self.artifacts / "chat-1" / "plots" / "sst 2017.html"
        target.write_bytes(PAGE + b"<!-- new -->")
        os.utime(target, (target.stat().st_atime, target.stat().st_mtime + 5))
        res = self.client.get(url, headers={"If-None-Match": etag})
        self.assertEqual(res.status_code, 200)
        self.assertNotEqual(res.headers["etag"], etag)
        self.assertTrue(res.content.startswith(PAGE + b"<!-- new -->"))

    def test_gzip_only_when_the_browser_accepts_it(self):
        url = "/api/v1/chats/chat-1/artifacts/view/plots/sst%202017.html"
        zipped = self.client.get(url, headers={"Accept-Encoding": "gzip"})
        self.assertEqual(zipped.headers["content-encoding"], "gzip")
        self.assertEqual(zipped.headers["vary"], "Accept-Encoding")
        self.assertTrue(zipped.content.startswith(PAGE))  # decoded by the client
        self.assertIn(b"weather-skills:figure-size", zipped.content)
        plain = self.client.get(url, headers={"Accept-Encoding": "identity"})
        self.assertNotIn("content-encoding", plain.headers)
        self.assertEqual(plain.content, zipped.content)

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


class HtmlProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.tmp.name) / "artifacts"
        self.root = self.artifacts / "chat-p"
        self.root.mkdir(parents=True)
        self.patch = patch("open_webui.utils.artifacts.ARTIFACTS_DIR", self.artifacts)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def _listing(self):
        return {item["path"]: item for item in list_artifacts("chat-p")}

    def test_plotly_page_provenance_is_listed(self):
        import html
        import json

        chain = [
            {"skill": "dynamical-fetch", "version": "0.0.4", "args": {"dataset": "imerg"}, "input": None},
            {"skill": "plot", "version": "1.0.0", "args": {"animate": True}, "input": "precip.zarr"},
        ]
        content = html.escape(json.dumps(chain), quote=True)
        (self.root / "plot.html").write_text(
            "<!doctype html><html><head>"
            f'<meta charset="utf-8"><meta name="weather_skills_history" content="{content}">'
            "</head><body><div>" + "x" * 2_000_000 + "</div></body></html>"
        )
        item = self._listing()["plot.html"]
        self.assertEqual(item["kind"], "html")
        self.assertEqual(item["provenance"], ["dynamical-fetch", "plot"])
        steps = item["provenance_detail"]["branches"][0]["steps"]
        self.assertEqual([s["skill"] for s in steps], ["dynamical-fetch", "plot"])
        self.assertEqual(steps[0]["args"], {"dataset": "imerg"})

    def test_page_without_provenance(self):
        (self.root / "page.html").write_text("<html><head><title>x</title></head><body></body></html>")
        self.assertNotIn("provenance", self._listing()["page.html"])

    def test_meta_outside_the_head_is_ignored(self):
        (self.root / "late.html").write_text(
            '<html><head></head><body><meta name="weather_skills_history" content="[]"></body></html>'
        )
        self.assertNotIn("provenance", self._listing()["late.html"])
