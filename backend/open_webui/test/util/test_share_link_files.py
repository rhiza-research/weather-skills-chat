"""A share link keeps its own copy of the chat's files, frozen like its messages."""

import asyncio
import tempfile
import unittest
import uuid
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

    def test_updating_the_share_replaces_the_snapshot(self):
        shared = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        (self.files / "map.png").write_bytes(b"v2")
        (self.artifacts / shared.id / "stale.txt").write_bytes(b"old")

        updated = Chats.update_shared_chat_by_chat_id(self.chat.id)

        snapshot = self.artifacts / updated.id
        self.assertEqual(updated.id, shared.id)
        self.assertEqual((snapshot / "map.png").read_bytes(), b"v2")
        self.assertFalse((snapshot / "stale.txt").exists())

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

    def test_removed_link_gives_nothing(self):
        Chats.delete_shared_chat_by_chat_id(self.chat.id)
        Chats.update_chat_share_id_by_id(self.chat.id, None)
        self.assertEqual(self.client.get(self.url(self.shared.id)).status_code, 401)


if __name__ == "__main__":
    unittest.main()
