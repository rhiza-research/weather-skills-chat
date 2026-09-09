"""Per-user uv cache paths for Landlock-confined skill runs."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from open_webui.utils.skill_runtime import (
    normalize_user_cache_id,
    run_skill,
    user_skill_cache_dir,
    user_skill_uv_dirs,
)


class UserCachePathTest(unittest.TestCase):
    def test_normalize_accepts_uuid_like_ids(self):
        uid = "e5f4dd61-c159-4b2a-9f0e-1234567890ab"
        self.assertEqual(normalize_user_cache_id(uid), uid)

    def test_normalize_rejects_traversal_and_separators(self):
        for bad in ("", "..", "../x", "a/b", "a\\b", ".hidden", None):
            with self.assertRaises(ValueError):
                normalize_user_cache_id(bad)

    def test_user_skill_cache_dir_creates_under_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "user_caches"
            path = user_skill_cache_dir("user-abc", caches_root=root)
            self.assertEqual(path, (root / "user-abc").resolve())
            self.assertTrue(path.is_dir())

    def test_user_skill_uv_dirs_are_distinct_subdirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "user_caches"
            uv_cache, uv_python = user_skill_uv_dirs("user-abc", caches_root=root)
            self.assertEqual(uv_cache, (root / "user-abc" / "uv-cache").resolve())
            self.assertEqual(uv_python, (root / "user-abc" / "python").resolve())
            self.assertNotEqual(uv_cache, uv_python)
            self.assertTrue(uv_cache.is_dir())
            self.assertTrue(uv_python.is_dir())


class RunSkillUserCacheWiringTest(unittest.TestCase):
    def test_sandboxed_run_points_uv_at_per_user_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifacts = tmp_path / "artifacts"
            caches = tmp_path / "user_caches"
            artifacts.mkdir()
            caches.mkdir()

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
                patch(
                    "open_webui.utils.skill_runtime.chat_sandbox",
                    side_effect=_sandbox,
                ),
                patch(
                    "open_webui.utils.skill_runtime.intermediate_results_dir",
                    side_effect=lambda cid: artifacts / cid / "intermediate_results",
                ),
                patch(
                    "open_webui.utils.skill_runtime.SKILL_SANDLOCK",
                    True,
                ),
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
                patch(
                    "asyncio.create_subprocess_exec",
                    side_effect=_fake_create,
                ),
            ):
                result = asyncio.run(
                    run_skill(
                        skill,
                        script="hello.py",
                        __user__={"id": "user-42"},
                        __metadata__={"chat_id": "chat-1"},
                        timeout=30,
                    )
                )

            expected = (caches / "user-42").resolve()
            expected_uv = expected / "uv-cache"
            expected_py = expected / "python"
            self.assertTrue(result.get("ok"), result)
            self.assertEqual(result.get("user_cache"), str(expected))
            self.assertTrue(expected.is_dir())
            self.assertEqual(captured["env"].get("UV_CACHE_DIR"), str(expected_uv))
            self.assertEqual(
                captured["env"].get("UV_PYTHON_INSTALL_DIR"), str(expected_py)
            )
            self.assertNotEqual(
                captured["env"].get("UV_CACHE_DIR"),
                captured["env"].get("UV_PYTHON_INSTALL_DIR"),
            )
            writable = [str(Path(p).resolve()) for p in captured["writable"]]
            self.assertIn(str(expected), writable)
            # Must not keep using the per-chat .uv-cache path.
            chat_uv = artifacts / "chat-1" / ".uv-cache"
            self.assertNotIn(str(chat_uv.resolve()), writable)

    def test_sandboxed_run_requires_user_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            artifacts = tmp_path / "artifacts"
            caches = tmp_path / "user_caches"
            artifacts.mkdir()
            caches.mkdir()
            skill = tmp_path / "skill"
            scripts = skill / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "hello.py").write_text("print('hi')\n", encoding="utf-8")

            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.utils.skill_runtime.USER_CACHES_DIR", caches),
                patch(
                    "open_webui.utils.skill_runtime.chat_sandbox",
                    side_effect=lambda cid: (artifacts / cid).mkdir(parents=True)
                    or (artifacts / cid),
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
            ):
                result = asyncio.run(
                    run_skill(
                        skill,
                        script="hello.py",
                        __user__={},
                        __metadata__={"chat_id": "chat-1"},
                    )
                )

            self.assertFalse(result.get("ok"))
            self.assertIn("user id", (result.get("stderr") or "").lower())


if __name__ == "__main__":
    unittest.main()
