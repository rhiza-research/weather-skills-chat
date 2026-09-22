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


class SecretUsageHintTest(unittest.TestCase):
    def test_hint_links_to_secrets_page_and_does_not_ask_for_values(self):
        from types import SimpleNamespace
        from open_webui.utils.secrets import secret_usage_hint

        user = SimpleNamespace(id="user-1")

        def metadata(_user, organization_id):
            if organization_id == "org-2":
                return [
                    {"name": "SHARED_KEY", "overridden": False},
                    {"name": "ECMWF_API_KEY", "overridden": True},
                    {"name": "PRIVATE_KEY", "overridden": False},
                ]
            return [{"name": "PERSONAL_KEY", "overridden": False}]

        with patch(
            "open_webui.utils.secrets.list_secret_metadata",
            side_effect=metadata,
        ):
            hint = secret_usage_hint(
                user, organization_id="org-2", webui_url="http://localhost:3000"
            )
            other = secret_usage_hint(user, webui_url="http://localhost:3000")
        self.assertIn("http://localhost:3000/workspace/secrets", hint)
        self.assertIn("secrets_page", hint)
        self.assertIn("{{secret:SHARED_KEY}}", hint)
        self.assertIn("{{secret:PRIVATE_KEY}}", hint)
        self.assertNotIn("{{secret:ECMWF_API_KEY}}", hint)
        self.assertNotIn("{{secret:PERSONAL_KEY}}", hint)
        self.assertIn("{{secret:PERSONAL_KEY}}", other)
        self.assertNotIn("{{secret:SHARED_KEY}}", other)
        self.assertNotIn("call create_secret", hint)
        self.assertIn("Do not ask the user to paste", hint)

        from open_webui.utils.secrets import secrets_page_url

        self.assertEqual(
            secrets_page_url("http://localhost:3000", "ECMWF_API_KEY"),
            "http://localhost:3000/workspace/secrets?name=ECMWF_API_KEY",
        )
        self.assertEqual(
            secrets_page_url("http://localhost:3000", "bad name"),
            "http://localhost:3000/workspace/secrets",
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


class ResolveEnvSecretsOrganizationTest(unittest.TestCase):
    def test_resolves_in_active_organization_and_does_not_inject_missing(self):
        from types import SimpleNamespace
        from open_webui.utils.skill_runtime import resolve_env_secrets_for_user

        seen = {}

        def fake_resolve(user, name, organization_id=None):
            seen["organization_id"] = organization_id
            if name == "MISSING":
                raise ValueError("nope")
            return "plaintext"

        user = SimpleNamespace(id="user-1")
        with (
            patch(
                "open_webui.models.users.Users.get_user_by_id",
                return_value=user,
            ),
            patch(
                "open_webui.utils.secrets.resolve_secret_value",
                side_effect=fake_resolve,
            ),
        ):
            resolved = resolve_env_secrets_for_user(
                ["ECMWF_API_KEY"],
                __user__={"id": "user-1"},
                organization_id="org-2",
            )
            self.assertEqual(resolved, {"ECMWF_API_KEY": "plaintext"})
            self.assertEqual(seen["organization_id"], "org-2")

            with self.assertRaises(ValueError) as ctx:
                resolve_env_secrets_for_user(
                    ["MISSING"],
                    __user__={"id": "user-1"},
                    organization_id="org-2",
                )
        self.assertIn("not injected", str(ctx.exception))
        self.assertIn("MISSING", str(ctx.exception))


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

    def test_missing_secret_is_not_injected(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)
            scripts = skill / "scripts"
            scripts.mkdir()
            (scripts / "main.py").write_text(
                "# /// script\n# requires-python = \">=3.11\"\n# dependencies = []\n# ///\nprint('ran')\n",
                encoding="utf-8",
            )
            seen = {}

            def fake_resolve(names, __user__=None, organization_id=None):
                seen["organization_id"] = organization_id
                raise ValueError(
                    "Secret(s) not available in the current organization and not injected: GONE"
                )

            with patch(
                "open_webui.utils.skill_runtime.resolve_env_secrets_for_user",
                side_effect=fake_resolve,
            ):
                result = asyncio.run(
                    run_skill(
                        skill,
                        env_secrets=["GONE"],
                        __user__={"id": "u1"},
                        __metadata__={"organization_id": "org-9"},
                    )
                )
            self.assertEqual(seen["organization_id"], "org-9")
            self.assertFalse(result["ok"])
            self.assertIn("not injected", result["stderr"])
            self.assertNotIn("ran", result.get("stdout") or "")


if __name__ == "__main__":
    unittest.main()
