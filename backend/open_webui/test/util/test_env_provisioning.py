"""Startup provisioning from SKILL_PACKS, CATALOG_MODELS and BOOTSTRAP_ADMIN_API_KEY."""

import asyncio
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy.exc import IntegrityError

from open_webui.models.models import ModelForm, ModelMeta, ModelParams, Models
from open_webui.models.organizations import (
    PLATFORM_ORG_ID,
    VISIBILITY_PUBLIC,
    Organizations,
)
from open_webui.models.skill_packs import SkillPacks
from open_webui.models.users import Users
from open_webui.utils import bootstrap
from open_webui.utils.auth import get_current_user_by_api_key
from open_webui.utils.bootstrap import provision_from_env
from open_webui.utils.skills import SkillInstallError, delete_skill_pack

PACK_URL = "https://github.com/example-org/example-skills"
PACK_URL_NORMALIZED = "https://github.com/example-org/example-skills.git"

PROVISIONING_VARS = (
    "SKILL_PACKS",
    "CATALOG_MODELS",
    "BOOTSTRAP_ADMIN_API_KEY",
    "BOOTSTRAP_ADMIN_EMAIL",
)


def _fake_checkout(local_path, git_url, git_ref):
    skill = Path(local_path) / "plot"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("---\nname: plot\n---\n# plot\n", encoding="utf-8")
    (skill / "scripts" / "run.py").write_text("print(1)\n", encoding="utf-8")
    return "0" * 40


def _model_entry(model_id: str, name: str) -> dict:
    return {
        "id": model_id,
        "base_model_id": "openai/gpt-4o",
        "name": name,
        "meta": {"description": "Weather agent"},
        "params": {"function_calling": "native"},
    }


def _new_user(test: unittest.TestCase, role: str = "pending", platform_role=None):
    """An account removed with everything it owns when the test ends."""
    email = f"owner-{uuid.uuid4().hex[:8]}@example.com"
    user = Users.insert_new_user(str(uuid.uuid4()), "Owner", email, role=role)
    test.addCleanup(Users.delete_user_by_id, user.id)
    if platform_role:
        Organizations.ensure_platform()
        Organizations.add_member(PLATFORM_ORG_ID, user.id, platform_role)
    return Users.get_user_by_id(user.id)


def _api_keys_enabled(enabled: bool):
    """Stand in for the ENABLE_API_KEY setting, which mock cannot patch in place."""
    return patch("open_webui.config.ENABLE_API_KEY", SimpleNamespace(value=enabled))


def _remove_model_later(test: unittest.TestCase, model_id: str) -> None:
    test.addCleanup(Models.delete_model_by_id, model_id)


class ProvisionFromEnvTest(unittest.TestCase):
    def setUp(self):
        self._env = patch.dict(os.environ, {})
        self._env.start()
        self.addCleanup(self._env.stop)
        for name in PROVISIONING_VARS:
            os.environ.pop(name, None)
        self.owner = _new_user(self, platform_role="admin")
        self.email = self.owner.email
        os.environ["BOOTSTRAP_ADMIN_EMAIL"] = self.email

        self._skills_dir = tempfile.TemporaryDirectory()
        self._skills_patch = patch(
            "open_webui.utils.skills.SKILLS_DIR", Path(self._skills_dir.name)
        )
        self._skills_patch.start()
        self._api_key_on = _api_keys_enabled(True)
        self._api_key_on.start()
        self.addCleanup(self._api_key_on.stop)

    def tearDown(self):
        for pack in SkillPacks.get_all():
            if pack.user_id == self.owner.id or pack.git_url == PACK_URL_NORMALIZED:
                delete_skill_pack(pack.id, {})
        self._skills_patch.stop()
        self._skills_dir.cleanup()

    def _install_patches(self):
        return (
            patch("open_webui.utils.skills.checkout_ref", side_effect=_fake_checkout),
            patch(
                "open_webui.utils.skills.load_tool_module_by_id",
                return_value=(MagicMock(), {}),
            ),
            patch("open_webui.utils.skills.get_tool_specs", return_value=[]),
        )

    def _provision_with_fake_git(self, tools=None):
        checkout, load, specs = self._install_patches()
        with checkout, load, specs:
            provision_from_env({} if tools is None else tools)

    def _pack(self, ref, url=PACK_URL_NORMALIZED):
        return SkillPacks.get_by_org_url_ref(PLATFORM_ORG_ID, url, ref)

    def test_nothing_set_does_nothing(self):
        os.environ.pop("BOOTSTRAP_ADMIN_EMAIL")
        provision_from_env({})

    def test_empty_lists_without_a_key_need_no_owner(self):
        os.environ.pop("BOOTSTRAP_ADMIN_EMAIL")
        os.environ["SKILL_PACKS"] = "[]"
        os.environ["CATALOG_MODELS"] = "[]"
        provision_from_env({})

    def test_new_pack_is_installed_public_in_platform_org(self):
        ref = f"main-{uuid.uuid4().hex[:6]}"
        os.environ["SKILL_PACKS"] = json.dumps([{"git_url": PACK_URL, "ref": ref}])
        tools = {}
        self._provision_with_fake_git(tools)

        pack = self._pack(ref)
        self.assertIsNotNone(pack)
        self.assertEqual(pack.visibility, VISIBILITY_PUBLIC)
        self.assertEqual(pack.user_id, self.owner.id)
        self.assertTrue(pack.enabled_by_default)
        self.assertEqual([s.name for s in pack.skills], ["plot"])
        self.assertTrue(tools)

    def test_ref_defaults_to_main(self):
        url = f"https://github.com/example-org/skills-{uuid.uuid4().hex[:8]}"
        os.environ["SKILL_PACKS"] = json.dumps([{"git_url": url}])
        self._provision_with_fake_git()
        self.assertIsNotNone(self._pack("main", url=f"{url}.git"))

    def test_enabled_by_default_false_is_applied(self):
        ref = f"main-{uuid.uuid4().hex[:6]}"
        os.environ["SKILL_PACKS"] = json.dumps(
            [{"git_url": PACK_URL, "ref": ref, "enabled_by_default": False}]
        )
        self._provision_with_fake_git()
        self.assertFalse(self._pack(ref).enabled_by_default)

    def test_existing_pack_is_not_fetched_and_takes_enabled_by_default(self):
        ref = f"main-{uuid.uuid4().hex[:6]}"
        os.environ["SKILL_PACKS"] = json.dumps([{"git_url": PACK_URL, "ref": ref}])
        self._provision_with_fake_git()
        before = self._pack(ref)

        os.environ["SKILL_PACKS"] = json.dumps(
            [{"git_url": PACK_URL, "ref": ref, "enabled_by_default": False}]
        )
        with patch("open_webui.utils.skills.checkout_ref") as checkout:
            provision_from_env({})
            checkout.assert_not_called()
        after = self._pack(ref)
        self.assertEqual(after.id, before.id)
        self.assertEqual(after.commit_sha, before.commit_sha)
        self.assertFalse(after.enabled_by_default)

    def test_pack_removed_from_the_variable_is_left_installed(self):
        ref = f"main-{uuid.uuid4().hex[:6]}"
        os.environ["SKILL_PACKS"] = json.dumps([{"git_url": PACK_URL, "ref": ref}])
        self._provision_with_fake_git()
        os.environ["SKILL_PACKS"] = "[]"
        provision_from_env({})
        self.assertIsNotNone(self._pack(ref))

    def test_failed_fetch_stops_startup_and_names_url_and_ref(self):
        ref = f"missing-{uuid.uuid4().hex[:6]}"
        os.environ["SKILL_PACKS"] = json.dumps([{"git_url": PACK_URL, "ref": ref}])
        with patch(
            "open_webui.utils.skills.checkout_ref",
            side_effect=SkillInstallError("fatal: couldn't find remote ref"),
        ):
            with self.assertRaises(RuntimeError) as raised:
                provision_from_env({})
        self.assertIn(PACK_URL, str(raised.exception))
        self.assertIn(ref, str(raised.exception))
        self.assertIsNone(self._pack(ref))

    def test_pack_installed_by_another_process_meanwhile_is_kept(self):
        ref = f"main-{uuid.uuid4().hex[:6]}"
        os.environ["SKILL_PACKS"] = json.dumps([{"git_url": PACK_URL, "ref": ref}])
        local_path = Path(self._skills_dir.name) / "other-process"
        _fake_checkout(local_path, PACK_URL_NORMALIZED, ref)

        def other_process_wins(*args, **kwargs):
            SkillPacks.insert(
                self.owner.id,
                name="example-skills",
                git_url=PACK_URL_NORMALIZED,
                git_ref=ref,
                commit_sha="0" * 40,
                local_path=str(local_path),
                organization_id=PLATFORM_ORG_ID,
                visibility=VISIBILITY_PUBLIC,
            )
            raise IntegrityError("INSERT", {}, Exception("unique constraint"))

        with patch(
            "open_webui.utils.skills.install_skill_pack", side_effect=other_process_wins
        ):
            provision_from_env({})
        self.assertIsNotNone(self._pack(ref))

    def test_invalid_pack_entry_stops_startup(self):
        for value in (
            "[{",
            "{}",
            json.dumps([{"url": PACK_URL}]),
            json.dumps([{"git_url": PACK_URL, "ref": ""}]),
            json.dumps([{"git_url": "git@github.com:example-org/example-skills.git"}]),
            json.dumps([{"git_url": "http://github.com/example-org/example-skills"}]),
            json.dumps(
                [
                    {"git_url": PACK_URL, "ref": "main"},
                    {"git_url": PACK_URL_NORMALIZED, "ref": "main"},
                ]
            ),
        ):
            with self.subTest(value=value):
                os.environ["SKILL_PACKS"] = value
                with self.assertRaisesRegex(ValueError, "SKILL_PACKS"):
                    provision_from_env({})

    def test_new_model_is_created_public_in_platform_org(self):
        model_id = f"weather-agent-{uuid.uuid4().hex[:6]}"
        _remove_model_later(self, model_id)
        os.environ["CATALOG_MODELS"] = json.dumps([_model_entry(model_id, "Weather")])
        provision_from_env({})

        model = Models.get_model_by_id(model_id)
        self.assertEqual(model.name, "Weather")
        self.assertEqual(model.base_model_id, "openai/gpt-4o")
        self.assertEqual(model.organization_id, PLATFORM_ORG_ID)
        self.assertEqual(model.visibility, VISIBILITY_PUBLIC)
        self.assertEqual(model.user_id, self.owner.id)
        self.assertEqual(model.params.model_dump()["function_calling"], "native")

    def test_model_may_name_the_platform_org_and_public_visibility(self):
        model_id = f"weather-agent-{uuid.uuid4().hex[:6]}"
        _remove_model_later(self, model_id)
        entry = {
            **_model_entry(model_id, "Weather"),
            "organization_id": PLATFORM_ORG_ID,
            "visibility": VISIBILITY_PUBLIC,
        }
        os.environ["CATALOG_MODELS"] = json.dumps([entry])
        provision_from_env({})
        self.assertEqual(Models.get_model_by_id(model_id).organization_id, PLATFORM_ORG_ID)

    def test_existing_model_is_overwritten_on_every_start(self):
        model_id = f"weather-agent-{uuid.uuid4().hex[:6]}"
        _remove_model_later(self, model_id)
        Models.insert_new_model(
            ModelForm(
                id=model_id,
                base_model_id="old/base",
                name="Edited in the app",
                meta=ModelMeta(description="old"),
                params=ModelParams(),
                organization_id="someone-else",
                visibility="organization",
            ),
            "someone-else",
        )
        os.environ["CATALOG_MODELS"] = json.dumps([_model_entry(model_id, "Weather")])
        provision_from_env({})
        provision_from_env({})

        model = Models.get_model_by_id(model_id)
        self.assertEqual(model.name, "Weather")
        self.assertEqual(model.base_model_id, "openai/gpt-4o")
        self.assertEqual(model.meta.description, "Weather agent")
        self.assertEqual(model.organization_id, PLATFORM_ORG_ID)
        self.assertEqual(model.visibility, VISIBILITY_PUBLIC)
        self.assertEqual(model.user_id, self.owner.id)

    def test_model_inserted_by_another_process_meanwhile_is_overwritten(self):
        model_id = f"weather-agent-{uuid.uuid4().hex[:6]}"
        _remove_model_later(self, model_id)
        Models.insert_new_model(
            ModelForm(
                id=model_id,
                name="Other process",
                meta=ModelMeta(),
                params=ModelParams(),
                organization_id=PLATFORM_ORG_ID,
                visibility=VISIBILITY_PUBLIC,
            ),
            "someone-else",
        )
        real_lookup = bootstrap._existing_model_row
        lookups = iter([lambda db, mid: None, real_lookup])
        os.environ["CATALOG_MODELS"] = json.dumps([_model_entry(model_id, "Weather")])
        with patch.object(
            bootstrap,
            "_existing_model_row",
            side_effect=lambda db, mid: next(lookups)(db, mid),
        ):
            provision_from_env({})
        model = Models.get_model_by_id(model_id)
        self.assertEqual(model.name, "Weather")
        self.assertEqual(model.user_id, self.owner.id)

    def test_model_removed_from_the_variable_is_left_in_place(self):
        model_id = f"weather-agent-{uuid.uuid4().hex[:6]}"
        _remove_model_later(self, model_id)
        os.environ["CATALOG_MODELS"] = json.dumps([_model_entry(model_id, "Weather")])
        provision_from_env({})
        os.environ["CATALOG_MODELS"] = "[]"
        provision_from_env({})
        self.assertIsNotNone(Models.get_model_by_id(model_id))

    def test_invalid_model_entry_stops_startup_before_any_write(self):
        model_id = f"weather-agent-{uuid.uuid4().hex[:6]}"
        _remove_model_later(self, model_id)
        cases = [
            [_model_entry(model_id, "Weather"), {"id": "no-name"}],
            [_model_entry(model_id, "Weather"), {**_model_entry("x", "X"), "typo": 1}],
            [{**_model_entry(model_id, "Weather"), "visibility": "organization"}],
            [_model_entry(model_id, "Weather"), _model_entry("  ", "Blank")],
            [_model_entry(model_id, "Weather"), _model_entry(model_id, "Twice")],
            {},
        ]
        for value in cases:
            with self.subTest(value=value):
                os.environ["CATALOG_MODELS"] = json.dumps(value)
                with self.assertRaisesRegex(ValueError, "CATALOG_MODELS"):
                    provision_from_env({})
                self.assertIsNone(Models.get_model_by_id(model_id))

    def test_api_key_is_set_on_every_start_and_authenticates(self):
        key = f"sk-{uuid.uuid4().hex}"
        os.environ["BOOTSTRAP_ADMIN_API_KEY"] = key
        provision_from_env({})
        Users.update_user_api_key_by_id(self.owner.id, f"sk-{uuid.uuid4().hex}")
        provision_from_env({})

        self.assertEqual(Users.get_user_api_key_by_id(self.owner.id), key)
        self.assertEqual(get_current_user_by_api_key(key).id, self.owner.id)

    def test_malformed_api_key_stops_startup(self):
        for value in ("not-a-key", "", "sk-", "sk-has space", "sk-tab\there", " sk-x"):
            with self.subTest(value=value):
                os.environ["BOOTSTRAP_ADMIN_API_KEY"] = value
                with self.assertRaisesRegex(ValueError, "BOOTSTRAP_ADMIN_API_KEY"):
                    provision_from_env({})

    def test_api_key_with_api_keys_turned_off_stops_startup(self):
        os.environ["BOOTSTRAP_ADMIN_API_KEY"] = f"sk-{uuid.uuid4().hex}"
        with _api_keys_enabled(False):
            with self.assertRaises(ValueError) as raised:
                provision_from_env({})
        self.assertIn("BOOTSTRAP_ADMIN_API_KEY", str(raised.exception))
        self.assertIn("ENABLE_API_KEY", str(raised.exception))

    def test_api_key_held_by_another_account_stops_startup(self):
        other = _new_user(self)
        key = f"sk-{uuid.uuid4().hex}"
        Users.update_user_api_key_by_id(other.id, key)
        os.environ["BOOTSTRAP_ADMIN_API_KEY"] = key
        with self.assertRaisesRegex(RuntimeError, "BOOTSTRAP_ADMIN_API_KEY"):
            provision_from_env({})
        self.assertEqual(Users.get_user_api_key_by_id(other.id), key)

    def test_missing_owner_stops_startup(self):
        os.environ["BOOTSTRAP_ADMIN_EMAIL"] = f"nobody-{uuid.uuid4().hex[:8]}@example.com"
        for name, value in (
            ("SKILL_PACKS", json.dumps([{"git_url": PACK_URL}])),
            ("CATALOG_MODELS", json.dumps([_model_entry("unused", "Unused")])),
            ("BOOTSTRAP_ADMIN_API_KEY", f"sk-{uuid.uuid4().hex}"),
        ):
            with self.subTest(name=name):
                os.environ[name] = value
                with self.assertRaisesRegex(RuntimeError, "BOOTSTRAP_ADMIN_EMAIL"):
                    provision_from_env({})
                os.environ.pop(name)

        os.environ.pop("BOOTSTRAP_ADMIN_EMAIL")
        os.environ["CATALOG_MODELS"] = json.dumps([_model_entry("unused", "Unused")])
        with self.assertRaisesRegex(RuntimeError, "BOOTSTRAP_ADMIN_EMAIL"):
            provision_from_env({})

    def test_owner_outside_the_platform_org_stops_startup(self):
        outsider = _new_user(self, role="user")
        os.environ["BOOTSTRAP_ADMIN_EMAIL"] = outsider.email
        os.environ["CATALOG_MODELS"] = json.dumps([_model_entry("unused", "Unused")])
        with self.assertRaisesRegex(RuntimeError, "platform organization"):
            provision_from_env({})
        self.assertIsNone(Models.get_model_by_id("unused"))


class LifespanProvisioningTest(unittest.TestCase):
    def test_app_serves_provisioned_catalog_and_accepts_the_api_key(self):
        import main
        from fastapi.testclient import TestClient

        owner = _new_user(self, role="admin", platform_role="admin")
        key = f"sk-{uuid.uuid4().hex}"
        ref = f"main-{uuid.uuid4().hex[:6]}"
        model_id = f"weather-agent-{uuid.uuid4().hex[:6]}"
        _remove_model_later(self, model_id)
        env = {
            "BOOTSTRAP_ADMIN_EMAIL": owner.email,
            "BOOTSTRAP_ADMIN_API_KEY": key,
            "SKILL_PACKS": json.dumps([{"git_url": PACK_URL, "ref": ref}]),
            "CATALOG_MODELS": json.dumps([_model_entry(model_id, "Weather")]),
        }
        skills_dir = tempfile.TemporaryDirectory()
        self.addCleanup(skills_dir.cleanup)

        async def no_cleanup():
            return None

        with (
            patch.dict(os.environ, env),
            _api_keys_enabled(True),
            patch("open_webui.utils.skills.SKILLS_DIR", Path(skills_dir.name)),
            patch("open_webui.utils.skills.checkout_ref", side_effect=_fake_checkout),
            patch(
                "open_webui.utils.skills.load_tool_module_by_id",
                return_value=(MagicMock(), {}),
            ),
            patch("open_webui.utils.skills.get_tool_specs", return_value=[]),
            patch("main.start_logger"),
            patch("main.periodic_usage_pool_cleanup", side_effect=no_cleanup),
            patch("main.ensure_retrieval_models"),
            patch("main._resync_skill_packs"),
            patch("open_webui.utils.chat_realtime.set_main_loop"),
            patch("open_webui.utils.automation_scheduler.start_scheduler"),
            patch("open_webui.utils.automation_scheduler.shutdown_scheduler"),
        ):
            with TestClient(main.app) as client:
                response = client.get(
                    "/api/v1/user_config",
                    headers={"Authorization": f"Bearer {key}"},
                )
                pack = SkillPacks.get_by_org_url_ref(
                    PLATFORM_ORG_ID, PACK_URL_NORMALIZED, ref
                )
                model = Models.get_model_by_id(model_id)

        if pack is not None:
            self.addCleanup(delete_skill_pack, pack.id, {})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNotNone(pack)
        self.assertEqual(pack.user_id, owner.id)
        self.assertEqual(pack.visibility, VISIBILITY_PUBLIC)
        self.assertIsNotNone(model)
        self.assertEqual(model.visibility, VISIBILITY_PUBLIC)

    def test_startup_fails_before_serving_when_provisioning_fails(self):
        import main

        async def start():
            async with main.lifespan(main.app):
                self.fail("the app started serving")

        with (
            patch.dict(os.environ, {"BOOTSTRAP_ADMIN_API_KEY": "not-a-key"}),
            patch("main.start_logger"),
            patch("open_webui.utils.chat_realtime.set_main_loop"),
            patch("open_webui.utils.automation_scheduler.start_scheduler") as scheduler,
        ):
            with self.assertRaisesRegex(ValueError, "BOOTSTRAP_ADMIN_API_KEY"):
                asyncio.run(start())
            scheduler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
