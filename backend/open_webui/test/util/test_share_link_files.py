"""A share link keeps its own copy of the chat's files, frozen like its messages."""

import asyncio
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.models.chats import ChatForm, Chats
from open_webui.routers import chats as chats_router


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

    def test_cloning_from_the_link_copies_the_snapshot_files(self):
        shared = Chats.insert_shared_chat_by_chat_id(self.chat.id)
        (self.files / "private.csv").write_bytes(b"later")
        viewer = SimpleNamespace(id=f"viewer-{uuid.uuid4()}", role="user")

        clone = asyncio.run(chats_router.clone_shared_chat_by_id(shared.id, viewer))
        self.addCleanup(Chats.delete_chat_by_id, clone.id)

        cloned = self.artifacts / clone.id
        self.assertEqual((cloned / "map.png").read_bytes(), b"v1")
        self.assertFalse((cloned / "private.csv").exists())


if __name__ == "__main__":
    unittest.main()
