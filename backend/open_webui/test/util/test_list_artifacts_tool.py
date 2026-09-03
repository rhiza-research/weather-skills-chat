from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from open_webui.utils.builtin_tools import list_artifacts


class ListArtifactsToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_lists_sandbox_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-list"
            root = artifacts / chat_id
            (root / "intermediate_results").mkdir(parents=True)
            (root / "notes.csv").write_text("a,b\n", encoding="utf-8")
            (root / "plots").mkdir()
            (root / "plots" / "map.png").write_bytes(b"png")

            user = MagicMock(id="u1")
            chat = MagicMock()
            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.utils.builtin_tools.Users") as users,
                patch("open_webui.utils.builtin_tools.Chats") as chats,
                patch("open_webui.utils.builtin_tools.can_read_chat", return_value=True),
            ):
                users.get_user_by_id.return_value = user
                chats.get_chat_by_id.return_value = chat
                out = await list_artifacts(
                    __user__={"id": "u1"},
                    __metadata__={"chat_id": chat_id},
                )

            self.assertIn("`notes.csv`", out)
            self.assertIn("`plots/`", out)
            self.assertIn("`plots/map.png`", out)
            self.assertIn("`intermediate_results/`", out)

    async def test_rejects_temporary_chat(self):
        out = await list_artifacts(__user__={"id": "u1"}, __metadata__={"chat_id": "local"})
        self.assertIn("temporary chat", out)
