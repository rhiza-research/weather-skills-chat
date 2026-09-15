"""Chat-local uv environments with JuiceFS package cache symlinks."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from open_webui.utils.skill_venvs import (
    ENVIRONMENTS_DIRNAME,
    chat_venv_dir,
    local_dir_size_bytes,
    lru_cleanup_skill_venvs,
    normalize_chat_venv_id,
    prepare_chat_uv_cache,
    skill_venvs_enabled,
)


class SkillVenvPathTest(unittest.TestCase):
    def test_normalize_accepts_uuid_like(self):
        cid = "e5f4dd61-c159-4b2a-9f0e-1234567890ab"
        self.assertEqual(normalize_chat_venv_id(cid), cid)

    def test_normalize_rejects_bad(self):
        for bad in ("", "..", "../x", "a/b", None):
            with self.assertRaises(ValueError):
                normalize_chat_venv_id(bad)

    def test_prepare_chat_uv_cache_symlinks_packages_keeps_envs_local(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            venvs = tmp_path / "venvs"
            shared = tmp_path / "shared-uv"
            venvs.mkdir()
            shared.mkdir()
            (shared / "wheels-v6").mkdir()
            (shared / "archive-v0").mkdir()
            (shared / ".lock").write_text("", encoding="utf-8")
            (shared / ENVIRONMENTS_DIRNAME).mkdir()
            (shared / ENVIRONMENTS_DIRNAME / "should-not-link").mkdir()

            chat_cache = prepare_chat_uv_cache("chat-1", shared, root=venvs)
            self.assertEqual(chat_cache, (venvs / "chat-1" / "uv-cache").resolve())
            self.assertTrue((chat_cache / "wheels-v6").is_symlink())
            self.assertEqual(
                (chat_cache / "wheels-v6").resolve(), (shared / "wheels-v6").resolve()
            )
            self.assertTrue((chat_cache / "archive-v0").is_symlink())
            # environments-v2 must be a real local directory, not a JuiceFS link.
            env_dir = chat_cache / ENVIRONMENTS_DIRNAME
            self.assertTrue(env_dir.is_dir())
            self.assertFalse(env_dir.is_symlink())
            self.assertFalse((env_dir / "should-not-link").exists())
            # .lock must stay local (not shared across chats).
            self.assertFalse((chat_cache / ".lock").exists())

    def test_local_dir_size_skips_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "chat"
            root.mkdir()
            (root / "real.bin").write_bytes(b"x" * 100)
            target = tmp_path / "big"
            target.mkdir()
            (target / "huge").write_bytes(b"y" * 10_000)
            (root / "link").symlink_to(target)
            self.assertEqual(local_dir_size_bytes(root), 100)

    def test_lru_evicts_oldest_until_under_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "venvs"
            root.mkdir()
            for i, name in enumerate(("old", "mid", "new")):
                d = root / name
                d.mkdir()
                (d / "env.bin").write_bytes(b"z" * 1000)
                os.utime(d, (1000 + i, 1000 + i))

            removed = lru_cleanup_skill_venvs(
                root=root,
                max_bytes=2500,
                protect_chat_id="new",
            )
            self.assertEqual(removed, ["old"])
            self.assertFalse((root / "old").exists())
            self.assertTrue((root / "mid").exists())
            self.assertTrue((root / "new").exists())

    def test_lru_skips_walk_when_disk_used_under_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "venvs"
            root.mkdir()
            huge = root / "chat"
            huge.mkdir()
            (huge / "blob").write_bytes(b"z" * 5000)

            class _Usage:
                total = 100_000
                used = 100
                free = 99_900

            with (
                patch(
                    "open_webui.utils.skill_venvs.shutil.disk_usage",
                    return_value=_Usage(),
                ),
                patch(
                    "open_webui.utils.skill_venvs.local_dir_size_bytes",
                    side_effect=AssertionError("should not walk"),
                ),
            ):
                removed = lru_cleanup_skill_venvs(root=root, max_bytes=1000)
            self.assertEqual(removed, [])
            self.assertTrue(huge.exists())

    def test_skill_venvs_enabled_requires_writable_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "venvs"
            self.assertFalse(skill_venvs_enabled(root=root))
            root.mkdir()
            self.assertTrue(skill_venvs_enabled(root=root))


class RunSkillChatVenvWiringTest(unittest.TestCase):
    def test_sandboxed_run_uses_chat_uv_cache_and_uv_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifacts = tmp_path / "artifacts"
            caches = tmp_path / "user_caches"
            venvs = tmp_path / "skill-venvs"
            artifacts.mkdir()
            caches.mkdir()
            venvs.mkdir()

            skill = tmp_path / "skill"
            scripts = skill / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "hello.py").write_text(
                "# /// script\n# requires-python = \">=3.11\"\n# dependencies = []\n# ///\n"
                "print('hi')\n",
                encoding="utf-8",
            )

            captured: dict = {}

            def _fake_launcher(**kwargs):
                captured["writable"] = list(kwargs.get("writable") or [])
                captured["readable"] = list(kwargs.get("readable") or [])
                captured["argv"] = list(kwargs.get("argv") or [])
                return ["true"]

            async def _fake_create(*_a, **kwargs):
                captured["env"] = kwargs.get("env") or {}
                proc = AsyncMock()
                proc.pid = 0
                proc.returncode = 0
                proc.communicate = AsyncMock(return_value=(b"hi\n", b""))
                return proc

            def _sandbox(cid: str) -> Path:
                root = artifacts / cid
                root.mkdir(parents=True, exist_ok=True)
                (root / "intermediate_results").mkdir(parents=True, exist_ok=True)
                return root

            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.utils.skill_runtime.USER_CACHES_DIR", caches),
                patch("open_webui.utils.skill_runtime.SKILL_VENV_ROOT", venvs),
                patch("open_webui.utils.skill_runtime.SKILL_VENV_MAX_BYTES", 0),
                patch(
                    "open_webui.utils.skill_runtime.chat_sandbox",
                    side_effect=_sandbox,
                ),
                patch(
                    "open_webui.utils.skill_runtime.intermediate_results_dir",
                    side_effect=lambda cid: artifacts / cid / "intermediate_results",
                ),
                patch("open_webui.utils.skill_runtime.SKILL_SANDLOCK", True),
                patch(
                    "open_webui.utils.skill_sandlock.select_landlock_backend",
                    return_value="landlock_only",
                ),
                patch(
                    "open_webui.utils.skill_sandlock.landlock_confinement_available",
                    return_value=True,
                ),
                patch(
                    "open_webui.utils.skill_sandlock.launcher_command",
                    side_effect=_fake_launcher,
                ),
                patch("asyncio.create_subprocess_exec", side_effect=_fake_create),
            ):
                from open_webui.utils.skill_runtime import run_skill

                result = asyncio.run(
                    run_skill(
                        skill,
                        script="hello.py",
                        __user__={"id": "user-42"},
                        __metadata__={"chat_id": "chat-9"},
                        timeout=30,
                    )
                )

            expected_chat = chat_venv_dir("chat-9", root=venvs)
            expected_uv = (expected_chat / "uv-cache").resolve()
            shared_uv = (caches / "user-42" / "uv-cache").resolve()
            self.assertTrue(result.get("ok"), result)
            self.assertEqual(result.get("chat_venv"), str(expected_chat))
            self.assertEqual(captured["env"].get("UV_CACHE_DIR"), str(expected_uv))
            self.assertEqual(captured["env"].get("UV_LINK_MODE"), "copy")
            self.assertNotEqual(captured["env"].get("UV_CACHE_DIR"), str(shared_uv))
            self.assertEqual(
                captured["argv"][:3],
                ["uv", "run", "--script"],
            )
            writable = [str(Path(p).resolve()) for p in captured["writable"]]
            self.assertIn(str(expected_chat.resolve()), writable)


if __name__ == "__main__":
    unittest.main()
