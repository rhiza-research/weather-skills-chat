"""Public share routes: a live share and its files load with no sign-in, nothing else does."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_webui.routers import artifacts as artifacts_router
from open_webui.routers import shares as shares_router

SHARE = "share-1"


class ShareRoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name) / SHARE
        (root / "plots").mkdir(parents=True)
        (root / "plots" / "map.html").write_text("<html></html>")
        (root / "notes.csv").write_text("a,b\n")
        self.chats = MagicMock()
        self.chats.is_live_share.return_value = True
        self.patches = [
            patch("open_webui.utils.artifacts.ARTIFACTS_DIR", Path(self.tmp.name)),
            patch("open_webui.routers.shares.Chats", self.chats),
            patch("open_webui.utils.organizations.Chats", self.chats),
        ]
        for p in self.patches:
            p.start()
        # No auth overrides: the share routes must work with no token at all.
        app = FastAPI()
        app.include_router(shares_router.router, prefix="/api/v1/shares")
        app.include_router(artifacts_router.router, prefix="/api/v1/chats")
        self.client = TestClient(app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def get(self, rest: str):
        return self.client.get(f"/api/v1/shares/{SHARE}{rest}")

    def test_a_live_share_and_its_files_load_signed_out(self):
        self.assertEqual(self.get("/artifacts").status_code, 200)
        self.assertEqual(self.get("/artifacts/content?path=notes.csv").content, b"a,b\n")
        self.assertEqual(self.get("/artifacts/view/plots/map.html").status_code, 200)
        self.assertEqual(self.get("/artifacts/archive?path=plots").status_code, 200)

    def test_an_expired_or_unknown_share_is_not_found(self):
        self.chats.is_live_share.return_value = False
        self.chats.get_chat_by_share_id.return_value = None
        self.assertEqual(self.get("").status_code, 404)
        self.assertEqual(self.get("/artifacts").status_code, 404)
        self.assertEqual(self.get("/artifacts/content?path=notes.csv").status_code, 404)

    def test_chat_routes_still_need_a_sign_in(self):
        res = self.client.get(f"/api/v1/chats/{SHARE}/artifacts/content?path=notes.csv")
        self.assertEqual(res.status_code, 403)

    def test_there_are_no_write_routes(self):
        methods = {m for r in shares_router.router.routes for m in r.methods}
        self.assertEqual(methods, {"GET"})


if __name__ == "__main__":
    unittest.main()
