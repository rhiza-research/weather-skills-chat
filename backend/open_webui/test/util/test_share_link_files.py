"""A share link keeps its own copy of the chat's files, frozen like its messages."""

import asyncio
import re
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from open_webui.models.chats import ChatForm, Chats
from open_webui.routers import artifacts as artifacts_router
from open_webui.routers import chats as chats_router
from open_webui.utils.auth import get_verified_user


class ShareLinkFilesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.artifacts = Path(tmp.name) / "artifacts"
        patcher = patch("open_webui.utils.artifacts.ARTIFACTS_DIR", self.artifacts)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.chat = Chats.insert_new_chat(
            f"user-{uuid.uuid4()}",
            ChatForm(chat={"title": "Rain", "history": {"currentId": None, "messages": {}}}),
        )
        self.addCleanup(Chats.delete_chat_by_id, self.chat.id)
        self.files = self.artifacts / self.chat.id
        self.files.mkdir(parents=True, exist_ok=True)
        (self.files / "map.png").write_bytes(b"v1")

    def test_sharing_snapshots_the_files_and_later_changes_stay_out(self):
        shared = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        (self.files / "map.png").write_bytes(b"v2")
        (self.files / "private.csv").write_bytes(b"later")

        snapshot = self.artifacts / shared.id
        self.assertEqual((snapshot / "map.png").read_bytes(), b"v1")
        self.assertFalse((snapshot / "private.csv").exists())

    def test_sharing_again_makes_a_new_link_and_keeps_the_old_one(self):
        first = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        (self.files / "map.png").write_bytes(b"v2")

        second = Chats.insert_shared_chat_by_chat_id(self.chat.id)

        self.assertNotEqual(first.id, second.id)
        self.assertEqual((self.artifacts / first.id / "map.png").read_bytes(), b"v1")
        self.assertEqual((self.artifacts / second.id / "map.png").read_bytes(), b"v2")
        self.assertTrue(Chats.is_live_share(first.id))
        self.assertEqual(Chats.get_chat_by_id(self.chat.id).share_id, second.id)

    def test_a_link_stops_working_when_it_expires(self):
        expired = Chats.insert_shared_chat_by_chat_id(self.chat.id, int(time.time()) - 1)
        live = Chats.insert_shared_chat_by_chat_id(self.chat.id, int(time.time()) + 3600)

        self.assertFalse(Chats.is_live_share(expired.id))
        self.assertIsNone(Chats.get_chat_by_share_id(expired.id))
        self.assertTrue(Chats.is_live_share(live.id))
        self.assertFalse(Chats.is_live_share(self.chat.id))

    def test_cleanup_deletes_only_expired_links_and_their_files(self):
        legacy = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        live = Chats.insert_shared_chat_by_chat_id(self.chat.id, int(time.time()) + 3600)
        expired = Chats.insert_shared_chat_by_chat_id(self.chat.id, int(time.time()) - 1)

        self.assertGreaterEqual(Chats.delete_expired_shared_chats(), 1)

        self.assertIsNone(Chats.get_chat_by_id(expired.id))
        self.assertFalse((self.artifacts / expired.id).exists())
        self.assertIsNone(Chats.get_chat_by_id(self.chat.id).share_id)
        for kept in (legacy, live):
            self.assertTrue(Chats.is_live_share(kept.id))
            self.assertTrue((self.artifacts / kept.id / "map.png").exists())

    def test_unsharing_and_deleting_the_chat_remove_the_snapshot(self):
        shared = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        self.assertTrue(Chats.delete_shared_chat_by_chat_id(self.chat.id))
        self.assertFalse((self.artifacts / shared.id).exists())

        Chats.update_chat_share_id_by_id(self.chat.id, None)
        shared = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        self.assertTrue(Chats.delete_chat_by_id(self.chat.id))
        self.assertFalse((self.artifacts / shared.id).exists())
        self.assertIsNone(Chats.get_chat_by_id(shared.id))

    def test_deleting_all_chats_removes_their_snapshots(self):
        shared = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        self.assertTrue((self.artifacts / shared.id / "map.png").exists())

        self.assertTrue(Chats.delete_chats_by_user_id(self.chat.user_id))

        self.assertFalse((self.artifacts / shared.id).exists())
        self.assertIsNone(Chats.get_chat_by_id(shared.id))

    def test_each_email_makes_a_new_seven_day_link(self):
        from open_webui.utils.builtin_tools import _create_chat_share_link

        old = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        (self.files / "map.png").write_bytes(b"v2")

        footer = _create_chat_share_link(self.chat.id, "https://chat.example")

        match = re.fullmatch(
            r"https://chat\.example/s/(\S+) \(expires (\w+ \d+, \d{4})\)", footer
        )
        self.assertIsNotNone(match, footer)
        share_id, date = match.groups()
        self.assertNotEqual(share_id, old.id)
        expires_at = Chats.get_chat_by_id(share_id).meta["expires_at"]
        self.assertAlmostEqual(expires_at, time.time() + 7 * 86400, delta=60)
        expires = datetime.fromtimestamp(expires_at, timezone.utc)
        self.assertEqual(date, f"{expires:%B} {expires.day}, {expires.year}")
        self.assertEqual((self.artifacts / share_id / "map.png").read_bytes(), b"v2")
        self.assertEqual((self.artifacts / old.id / "map.png").read_bytes(), b"v1")

    def test_cloning_from_the_link_copies_the_snapshot_files(self):
        shared = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        (self.files / "private.csv").write_bytes(b"later")
        viewer = SimpleNamespace(id=f"viewer-{uuid.uuid4()}", role="user")

        clone = asyncio.run(
            chats_router.clone_shared_chat_by_id(shared.id, viewer, organization_id=viewer.id)
        )
        self.addCleanup(Chats.delete_chat_by_id, clone.id)

        cloned = self.artifacts / clone.id
        self.assertEqual((cloned / "map.png").read_bytes(), b"v1")
        self.assertFalse((cloned / "private.csv").exists())


class ShareRouteTest(unittest.TestCase):
    """The owner picks how long a new link lasts, within the allowed range."""

    def setUp(self):
        ShareLinkFilesTest.setUp(self)
        app = FastAPI()
        app.include_router(chats_router.router, prefix="/chats")
        owner = SimpleNamespace(id=self.chat.user_id, role="user")
        app.dependency_overrides[get_verified_user] = lambda: owner
        self.client = TestClient(app)

    def share(self, **body):
        return self.client.post(f"/chats/{self.chat.id}/share", json=body or None)

    def test_the_link_expires_after_the_chosen_days(self):
        for body, days in (({}, 7), ({"expires_in_days": 30}, 30)):
            res = self.share(**body)
            self.assertEqual(res.status_code, 200)
            expires_at = res.json()["meta"]["expires_at"]
            self.assertAlmostEqual(expires_at, time.time() + days * 86400, delta=60)

    def test_lengths_outside_the_range_are_refused(self):
        for days in (0, 366):
            self.assertEqual(self.share(expires_in_days=days).status_code, 422)


class ShareLinkFileRoutesTest(unittest.TestCase):
    """Anyone who can open the link reads the snapshot's files; no one writes them."""

    def setUp(self):
        ShareLinkFilesTest.setUp(self)
        self.shared = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        (self.files / "map.png").write_bytes(b"v2")
        (self.files / "private.csv").write_bytes(b"later")
        app = FastAPI()
        app.include_router(artifacts_router.router, prefix="/chats")
        viewer = SimpleNamespace(id=f"viewer-{uuid.uuid4()}", role="user")
        app.dependency_overrides[get_verified_user] = lambda: viewer
        self.client = TestClient(app)

    def url(self, chat_id, rest=""):
        return f"/chats/{chat_id}/artifacts{rest}"

    def test_link_holder_lists_and_downloads_the_snapshot(self):
        listed = self.client.get(self.url(self.shared.id))
        self.assertEqual(listed.status_code, 200)
        paths = [f["path"] for f in listed.json()]
        self.assertIn("map.png", paths)
        self.assertNotIn("private.csv", paths)

        content = self.client.get(self.url(self.shared.id, "/content?path=map.png"))
        self.assertEqual(content.status_code, 200)
        self.assertEqual(content.content, b"v1")

    def test_live_files_stay_out_of_reach(self):
        missing = self.client.get(self.url(self.shared.id, "/content?path=private.csv"))
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(self.client.get(self.url(self.chat.id)).status_code, 401)

    def test_no_one_writes_to_the_snapshot(self):
        upload = self.client.post(
            self.url(self.shared.id),
            data={"path": "map.png"},
            files={"file": ("map.png", b"evil")},
        )
        self.assertEqual(upload.status_code, 401)
        snapshot = self.artifacts / self.shared.id / "map.png"
        self.assertEqual(snapshot.read_bytes(), b"v1")

    def test_expired_link_gives_nothing(self):
        expired = Chats.insert_shared_chat_by_chat_id(self.chat.id, int(time.time()) - 1)
        self.assertEqual(self.client.get(self.url(expired.id)).status_code, 401)

    def test_removed_link_gives_nothing(self):
        Chats.delete_shared_chat_by_chat_id(self.chat.id)
        Chats.update_chat_share_id_by_id(self.chat.id, None)
        self.assertEqual(self.client.get(self.url(self.shared.id)).status_code, 401)


if __name__ == "__main__":
    unittest.main()
