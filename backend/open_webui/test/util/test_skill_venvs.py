"""Chat-scoped local skill venvs (JuiceFS UV_CACHE_DIR, local site-packages)."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from open_webui.utils.skill_venvs import (
    chat_venv_dir,
    ensure_chat_script_venv,
    local_dir_size_bytes,
    lru_cleanup_skill_venvs,
    normalize_chat_venv_id,
    script_env_key,
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

    def test_script_env_key_stable_and_lock_sensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "s.py"
            script.write_text(
                "# /// script\n# requires-python = \">=3.11\"\n# dependencies = []\n# ///\n"
                "print(1)\n",
                encoding="utf-8",
            )
            k1 = script_env_key(script)
            k2 = script_env_key(script)
            self.assertEqual(k1, k2)
            lock = Path(str(script) + ".lock")
            lock.write_text("version = 1\n", encoding="utf-8")
            self.assertNotEqual(script_env_key(script), k1)

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

    def test_skill_venvs_enabled_requires_writable_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "venvs"
            self.assertFalse(skill_venvs_enabled(root=root))
            root.mkdir()
            self.assertTrue(skill_venvs_enabled(root=root))

    def test_ensure_chat_script_venv_creates_and_reuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            venvs = tmp_path / "venvs"
            cache = tmp_path / "uv-cache"
            py = tmp_path / "python"
            venvs.mkdir()
            cache.mkdir()
            py.mkdir()
            script = tmp_path / "hello.py"
            script.write_text(
                "# /// script\n# requires-python = \">=3.11\"\n# dependencies = []\n# ///\n"
                "print('hi')\n",
                encoding="utf-8",
            )

            calls: list[list[str]] = []

            def _fake_run(args, *, env, cwd=None):
                calls.append(list(args))
                if args[0] == "venv":
                    venv = Path(args[1])
                    (venv / "bin").mkdir(parents=True)
                    (venv / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
                    (venv / "bin" / "python").chmod(0o755)
                elif args[0] == "export":
                    out = Path(args[args.index("-o") + 1])
                    out.write_text("#\n", encoding="utf-8")
                elif args[0] == "pip":
                    return
                else:
                    raise AssertionError(args)

            with patch("open_webui.utils.skill_venvs._run_uv", side_effect=_fake_run):
                uv_env = {
                    "UV_CACHE_DIR": str(cache),
                    "UV_PYTHON_INSTALL_DIR": str(py),
                }
                v1 = ensure_chat_script_venv(
                    "chat-1", script, uv_env=uv_env, root=venvs
                )
                v2 = ensure_chat_script_venv(
                    "chat-1", script, uv_env=uv_env, root=venvs
                )
            self.assertEqual(v1, v2)
            self.assertTrue((v1 / "bin" / "python").is_file())
            # First call: venv + export + pip; second should reuse (no new uv calls).
            self.assertEqual([c[0] for c in calls], ["venv", "export", "pip"])
            self.assertTrue(str(v1).startswith(str((venvs / "chat-1" / "envs").resolve())))


class RunSkillChatVenvWiringTest(unittest.TestCase):
    def test_sandboxed_run_uses_local_python_keeps_juicefs_uv_cache(self):
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
            fake_venv = venvs / "chat-9" / "envs" / "abc"
            fake_venv.mkdir(parents=True)
            (fake_venv / "bin").mkdir()
            (fake_venv / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")

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
                patch(
                    "open_webui.utils.skill_runtime.ensure_chat_script_venv",
                    return_value=fake_venv,
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
            shared_uv = (caches / "user-42" / "uv-cache").resolve()
            self.assertTrue(result.get("ok"), result)
            self.assertEqual(result.get("chat_venv"), str(expected_chat))
            self.assertEqual(captured["env"].get("UV_CACHE_DIR"), str(shared_uv))
            self.assertEqual(
                captured["argv"][:2],
                [str(fake_venv / "bin" / "python"), str((scripts / "hello.py").resolve())],
            )
            writable = [str(Path(p).resolve()) for p in captured["writable"]]
            self.assertIn(str(expected_chat.resolve()), writable)


if __name__ == "__main__":
    unittest.main()
