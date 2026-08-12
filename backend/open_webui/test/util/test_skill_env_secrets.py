"""Lightweight unit checks for skill env_secrets injection helpers."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_webui.utils.skill_runtime import (
    _redact_skill_result,
    normalize_env_secret_names,
    run_skill,
)


class NormalizeEnvSecretNamesTest(unittest.TestCase):
    def test_strip_dedupe_preserve_order(self):
        self.assertEqual(
            normalize_env_secret_names([" A ", "A", "B", "", None, "B"]),
            ["A", "B"],
        )

    def test_empty(self):
        self.assertEqual(normalize_env_secret_names(None), [])
        self.assertEqual(normalize_env_secret_names([]), [])

    def test_rejects_unsafe_names(self):
        with self.assertRaises(ValueError):
            normalize_env_secret_names(["bad-name"])
        with self.assertRaises(ValueError):
            normalize_env_secret_names(["1LEADING"])
        with self.assertRaises(ValueError):
            normalize_env_secret_names(["HAS SPACE"])


class RedactSkillResultTest(unittest.TestCase):
    def test_redacts_stdout_stderr(self):
        result = _redact_skill_result(
            {
                "ok": True,
                "stdout": "token=sekrit-value",
                "stderr": "also sekrit-value here",
                "argv": ["--x", "sekrit-value"],
            },
            {"SMOKE_TOKEN": "sekrit-value"},
        )
        self.assertNotIn("sekrit-value", result["stdout"])
        self.assertNotIn("sekrit-value", result["stderr"])
        self.assertIn("{{secret:SMOKE_TOKEN}}", result["stdout"])
        self.assertIn("{{secret:SMOKE_TOKEN}}", result["stderr"])
        self.assertEqual(result["argv"], ["--x", "{{secret:SMOKE_TOKEN}}"])


class RunSkillEnvSecretsTest(unittest.TestCase):
    def test_invalid_name_errors_without_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)
            (skill / "scripts").mkdir()
            (skill / "scripts" / "main.py").write_text(
                "# /// script\n# requires-python = \">=3.11\"\n# dependencies = []\n# ///\nprint('hi')\n",
                encoding="utf-8",
            )
            result = asyncio.run(
                run_skill(skill, env_secrets=["not-valid!"], __user__={"id": "u1"})
            )
            self.assertFalse(result["ok"])
            self.assertIn("Invalid env_secrets", result["stderr"])

    def test_injects_and_redacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)
            scripts = skill / "scripts"
            scripts.mkdir()
            (scripts / "check_env.py").write_text(
                "# /// script\n"
                "# requires-python = \">=3.11\"\n"
                "# dependencies = []\n"
                "# ///\n"
                "import os, sys\n"
                "val = os.environ.get('SMOKE_TOKEN')\n"
                "if not val:\n"
                "    print('MISSING')\n"
                "    sys.exit(1)\n"
                "print('PRESENT')\n"
                "print(f'leaked:{val}', file=sys.stderr)\n",
                encoding="utf-8",
            )

            async def _run():
                with patch(
                    "open_webui.utils.skill_runtime.resolve_env_secrets_for_user",
                    return_value={"SMOKE_TOKEN": "super-secret-value"},
                ):
                    return await run_skill(
                        skill,
                        script="check_env.py",
                        env_secrets=["SMOKE_TOKEN"],
                        __user__={"id": "u1"},
                        __metadata__={},
                    )

            result = asyncio.run(_run())
            self.assertTrue(result.get("ok"), result)
            self.assertIn("PRESENT", result.get("stdout") or "")
            self.assertNotIn("super-secret-value", result.get("stderr") or "")
            self.assertIn("{{secret:SMOKE_TOKEN}}", result.get("stderr") or "")
            self.assertEqual(result.get("env_secrets"), ["SMOKE_TOKEN"])


if __name__ == "__main__":
    unittest.main()
