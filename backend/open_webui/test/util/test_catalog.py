"""Catalog visibility, enable overrides, and can_add gating."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.models.organizations import (
    PLATFORM_ORG_ID,
    VISIBILITY_ORGANIZATION,
    VISIBILITY_PUBLIC,
)
from open_webui.models.org_catalog import RESOURCE_MODEL, RESOURCE_SKILL
from open_webui.utils.catalog import (
    annotate_skills,
    can_create_private,
    can_manage_public,
    effective_enabled,
    is_catalog_chat_model,
    is_usable,
    is_visible,
    skill_effective_enabled,
    skill_is_usable,
    skill_is_visible,
    stamp_create,
)
from open_webui.utils.models import check_model_access


def _item(**kwargs):
    defaults = {
        "id": "item-1",
        "organization_id": PLATFORM_ORG_ID,
        "visibility": VISIBILITY_PUBLIC,
        "enabled_by_default": True,
        "base_model_id": "openai/gpt-4o",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class CatalogVisibilityTest(unittest.TestCase):
    def test_public_visible_when_default_on_and_no_override(self):
        item = _item(enabled_by_default=True)
        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get", return_value=None
        ):
            self.assertTrue(is_visible("org-a", RESOURCE_MODEL, item))
            self.assertTrue(is_usable("org-a", RESOURCE_MODEL, item))
            self.assertTrue(effective_enabled("org-a", RESOURCE_MODEL, item))

    def test_public_listed_but_unusable_when_override_off(self):
        item = _item(enabled_by_default=True)
        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get", return_value=False
        ):
            self.assertTrue(is_visible("org-a", RESOURCE_MODEL, item))
            self.assertFalse(is_usable("org-a", RESOURCE_MODEL, item))
            self.assertFalse(effective_enabled("org-a", RESOURCE_MODEL, item))

    def test_public_disabled_by_default_still_listed(self):
        item = _item(enabled_by_default=False)
        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get", return_value=None
        ):
            self.assertTrue(is_visible("org-a", RESOURCE_MODEL, item))
            self.assertFalse(is_usable("org-a", RESOURCE_MODEL, item))
            self.assertFalse(effective_enabled("org-a", RESOURCE_MODEL, item))

    def test_inactive_public_hidden_from_user_catalog(self):
        item = _item(is_active=False)
        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get", return_value=True
        ):
            self.assertFalse(is_visible("org-a", RESOURCE_MODEL, item))
            self.assertFalse(is_usable("org-a", RESOURCE_MODEL, item))
            self.assertFalse(is_usable(PLATFORM_ORG_ID, RESOURCE_MODEL, item))
            self.assertTrue(is_visible(PLATFORM_ORG_ID, RESOURCE_MODEL, item))

    def test_explicit_override_survives_default_change(self):
        item = _item(enabled_by_default=False)
        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get", return_value=True
        ):
            self.assertTrue(is_visible("org-a", RESOURCE_MODEL, item))
            self.assertTrue(is_usable("org-a", RESOURCE_MODEL, item))

    def test_org_private_never_leaks(self):
        item = _item(
            organization_id="org-a",
            visibility=VISIBILITY_ORGANIZATION,
        )
        self.assertTrue(is_visible("org-a", RESOURCE_MODEL, item))
        self.assertTrue(is_usable("org-a", RESOURCE_MODEL, item))
        self.assertFalse(is_visible("org-b", RESOURCE_MODEL, item))
        self.assertFalse(is_usable("org-b", RESOURCE_MODEL, item))

    def test_personal_org_toggle_is_scoped(self):
        item = _item()

        def get_override(organization_id, resource_type, resource_id):
            return False if organization_id == "alice" else None

        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get",
            side_effect=get_override,
        ):
            self.assertTrue(is_visible("alice", RESOURCE_MODEL, item))
            self.assertFalse(is_usable("alice", RESOURCE_MODEL, item))
            self.assertTrue(is_visible("bob", RESOURCE_MODEL, item))
            self.assertTrue(is_usable("bob", RESOURCE_MODEL, item))


class CatalogPermissionTest(unittest.TestCase):
    def test_can_add_false_rejects_create(self):
        user = SimpleNamespace(id="alice")
        org = SimpleNamespace(id="org-a", can_add_models=False)
        with patch(
            "open_webui.utils.catalog.is_org_admin", return_value=True
        ), patch(
            "open_webui.utils.catalog.Organizations.get_organization_by_id",
            return_value=org,
        ), patch(
            "open_webui.utils.catalog.is_platform_admin", return_value=False
        ):
            self.assertFalse(can_create_private(user, "org-a", RESOURCE_MODEL))
            with self.assertRaises(PermissionError):
                stamp_create(user, "org-a", RESOURCE_MODEL)

    def test_can_add_true_stamps_org_private(self):
        user = SimpleNamespace(id="alice")
        org = SimpleNamespace(id="org-a", can_add_models=True)
        with patch(
            "open_webui.utils.catalog.is_org_admin", return_value=True
        ), patch(
            "open_webui.utils.catalog.Organizations.get_organization_by_id",
            return_value=org,
        ), patch(
            "open_webui.utils.catalog.is_platform_admin", return_value=False
        ):
            org_id, visibility = stamp_create(user, "org-a", RESOURCE_MODEL)
            self.assertEqual(org_id, "org-a")
            self.assertEqual(visibility, VISIBILITY_ORGANIZATION)

    def test_platform_admin_in_platform_stamps_public(self):
        user = SimpleNamespace(id="admin")
        with patch(
            "open_webui.utils.catalog.is_platform_admin", return_value=True
        ):
            self.assertTrue(can_manage_public(user, PLATFORM_ORG_ID))
            org_id, visibility = stamp_create(user, PLATFORM_ORG_ID, RESOURCE_MODEL)
            self.assertEqual(org_id, PLATFORM_ORG_ID)
            self.assertEqual(visibility, VISIBILITY_PUBLIC)

    def test_platform_admin_outside_platform_cannot_manage_public(self):
        user = SimpleNamespace(id="admin")
        with patch(
            "open_webui.utils.catalog.is_platform_admin", return_value=True
        ):
            self.assertFalse(can_manage_public(user, "org-a"))


class CatalogChatPickerTest(unittest.TestCase):
    def test_raw_connection_models_are_not_catalog_chat_models(self):
        self.assertFalse(is_catalog_chat_model(None))
        self.assertFalse(is_catalog_chat_model(_item(base_model_id=None)))
        self.assertTrue(is_catalog_chat_model(_item(base_model_id="openai/gpt-4o")))

    def test_check_model_access_rejects_raw_connection_ids(self):
        user = SimpleNamespace(id="alice")
        with patch(
            "open_webui.utils.models.Models.get_model_by_id", return_value=None
        ):
            with self.assertRaises(Exception):
                check_model_access(user, {"id": "openai/gpt-4o"}, "org-a")

    def test_check_model_access_accepts_visible_catalog_model(self):
        user = SimpleNamespace(id="alice")
        model_info = _item(id="wrapper")
        with patch(
            "open_webui.utils.models.Models.get_model_by_id", return_value=model_info
        ), patch(
            "open_webui.utils.models.is_usable", return_value=True
        ):
            check_model_access(user, {"id": "wrapper"}, "org-a")

    def test_check_model_access_rejects_hidden_catalog_model(self):
        user = SimpleNamespace(id="alice")
        model_info = _item(id="wrapper")
        with patch(
            "open_webui.utils.models.Models.get_model_by_id", return_value=model_info
        ), patch(
            "open_webui.utils.models.is_usable", return_value=False
        ):
            with self.assertRaises(Exception):
                check_model_access(user, {"id": "wrapper"}, "org-a")


def _pack(**kwargs):
    defaults = {
        "id": "pack-1",
        "organization_id": PLATFORM_ORG_ID,
        "visibility": VISIBILITY_PUBLIC,
        "enabled_by_default": True,
        "is_active": True,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _skill(**kwargs):
    defaults = {
        "name": "plot",
        "tool_id": "skill_plot",
        "enabled": True,
        "enabled_by_default": True,
        "is_active": True,
    }
    defaults.update(kwargs)
    return defaults


class SkillCatalogTest(unittest.TestCase):
    def test_inactive_skill_hidden_from_org_listed_on_platform(self):
        pack = _pack()
        skill = _skill(is_active=False)
        self.assertFalse(skill_is_visible("org-a", pack, skill))
        self.assertTrue(skill_is_visible(PLATFORM_ORG_ID, pack, skill))
        self.assertFalse(skill_is_usable("org-a", pack, skill))

    def test_disabled_skill_still_listed(self):
        pack = _pack()
        skill = _skill(enabled_by_default=False, enabled=False)
        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get", return_value=None
        ):
            self.assertTrue(skill_is_visible("org-a", pack, skill))
            self.assertFalse(skill_is_usable("org-a", pack, skill))
            self.assertFalse(skill_effective_enabled("org-a", skill))

    def test_skill_org_override_survives_default_off(self):
        pack = _pack()
        skill = _skill(enabled_by_default=False, enabled=False)
        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get", return_value=True
        ):
            self.assertTrue(skill_is_visible("org-a", pack, skill))
            self.assertTrue(skill_is_usable("org-a", pack, skill))
            self.assertTrue(skill_effective_enabled("org-a", skill))

    def test_unusable_pack_makes_skill_unusable(self):
        pack = _pack(is_active=False)
        skill = _skill()
        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get", return_value=True
        ):
            self.assertFalse(is_usable("org-a", RESOURCE_SKILL, pack))
            self.assertFalse(skill_is_usable("org-a", pack, skill))

    def test_annotate_skills_filters_inactive_for_org(self):
        pack = _pack()
        skills = [
            _skill(tool_id="on", is_active=True),
            _skill(name="hidden", tool_id="off", is_active=False),
        ]
        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get", return_value=None
        ):
            org_list = annotate_skills(pack, "org-a", skills)
            admin_list = annotate_skills(pack, PLATFORM_ORG_ID, skills)
        self.assertEqual([s["tool_id"] for s in org_list], ["on"])
        self.assertEqual([s["tool_id"] for s in admin_list], ["on", "off"])
        self.assertFalse(admin_list[1]["is_active"])

    def test_legacy_enabled_becomes_default(self):
        pack = _pack()
        skill = {"name": "plot", "tool_id": "skill_plot", "enabled": False}
        with patch(
            "open_webui.utils.catalog.OrgCatalogOverrides.get", return_value=None
        ):
            annotated = annotate_skills(pack, "org-a", [skill])
        self.assertEqual(len(annotated), 1)
        self.assertFalse(annotated[0]["enabled_by_default"])
        self.assertFalse(annotated[0]["enabled"])


if __name__ == "__main__":
    unittest.main()
