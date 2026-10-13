from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from open_webui.utils.builtin_tools import (
    display_image,
    looks_like_display_image,
    wait_for_sandbox_image,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class LooksLikeDisplayImageTest(unittest.TestCase):
    def test_png_jpeg_gif_webp(self):
        self.assertTrue(looks_like_display_image(PNG, ".png"))
        self.assertTrue(looks_like_display_image(b"\xff\xd8\xff\xe0rest", ".jpg"))
        self.assertTrue(looks_like_display_image(b"GIF89a....", ".gif"))
        self.assertTrue(looks_like_display_image(b"RIFF\x00\x00\x00\x00WEBP....", ".webp"))

    def test_empty_and_wrong_magic_are_rejected(self):
        self.assertFalse(looks_like_display_image(b"", ".png"))
        self.assertFalse(looks_like_display_image(b"{}", ".png"))
        self.assertFalse(looks_like_display_image(b"PK\x03\x04zip", ".png"))


class WaitForSandboxImageTest(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_file_to_appear_with_magic(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plot.png"

            async def writer():
                await asyncio.sleep(0.05)
                target.write_bytes(PNG)

            task = asyncio.create_task(writer())
            data = await wait_for_sandbox_image(
                target, ".png", timeout_s=1.0, interval_s=0.02
            )
            await task
            self.assertEqual(data, PNG)

    async def test_ignores_empty_placeholder_until_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "plot.png"
            target.write_bytes(b"")

            async def writer():
                await asyncio.sleep(0.05)
                target.write_bytes(PNG)

            task = asyncio.create_task(writer())
            data = await wait_for_sandbox_image(
                target, ".png", timeout_s=1.0, interval_s=0.02
            )
            await task
            self.assertEqual(data, PNG)

    async def test_timeout_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "missing.png"
            data = await wait_for_sandbox_image(
                target, ".png", timeout_s=0.08, interval_s=0.02
            )
            self.assertIsNone(data)


class DisplayImageToolTest(unittest.IsolatedAsyncioTestCase):
    async def test_returns_data_url_for_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-img"
            root = artifacts / chat_id
            (root / "intermediate_results").mkdir(parents=True)
            (root / "plot.png").write_bytes(PNG)

            user = MagicMock(id="u1")
            chat = MagicMock()
            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.utils.builtin_tools.Users") as users,
                patch("open_webui.utils.builtin_tools.Chats") as chats,
                patch("open_webui.utils.builtin_tools.can_read_chat", return_value=True),
                patch("open_webui.utils.builtin_tools.DISPLAY_IMAGE_WAIT_S", 0.2),
                patch("open_webui.utils.builtin_tools.DISPLAY_IMAGE_POLL_S", 0.02),
            ):
                users.get_user_by_id.return_value = user
                chats.get_chat_by_id.return_value = chat
                out = await display_image(
                    "plot.png",
                    __user__={"id": "u1"},
                    __metadata__={"chat_id": chat_id},
                )

            self.assertIsInstance(out, list)
            self.assertIn("plot.png", out[0])
            self.assertTrue(out[1].startswith("data:image/png;base64,"))
