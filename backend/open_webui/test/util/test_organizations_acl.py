"""Organization tenancy and ACL helpers."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.models.organizations import (
    ORG_KIND_PERSONAL,
    ORG_KIND_WORKSPACE,
    PLATFORM_ORG_ID,
    VISIBILITY_ORGANIZATION,
    VISIBILITY_PRIVATE,
)
from open_webui.utils.organizations import (
    can_read_chat,
    can_read_org_resource,
    can_write_chat,
    can_write_org_resource,
    resolve_visibility,
)


class ResolveVisibilityTest(unittest.TestCase):
    def test_personal_org_forces_private(self):
        org = SimpleNamespace(kind=ORG_KIND_PERSONAL)
        with patch(
            "open_webui.utils.organizations.Organizations.get_organization_by_id",
            return_value=org,
        ):
            self.assertEqual(
                resolve_visibility("user-1", VISIBILITY_ORGANIZATION),
                VISIBILITY_PRIVATE,
            )

    def test_workspace_keeps_organization_visibility(self):
        org = SimpleNamespace(kind=ORG_KIND_WORKSPACE)
        with patch(
            "open_webui.utils.organizations.Organizations.get_organization_by_id",
            return_value=org,
        ):
            self.assertEqual(
                resolve_visibility("org-1", VISIBILITY_ORGANIZATION),
                VISIBILITY_ORGANIZATION,
            )


class ChatAclTest(unittest.TestCase):
    def test_creator_can_read_and_write_private(self):
        user = SimpleNamespace(id="alice")
        chat = SimpleNamespace(
            user_id="alice",
            organization_id="org",
            visibility=VISIBILITY_PRIVATE,
        )
        self.assertTrue(can_read_chat(user, chat))
        self.assertTrue(can_write_chat(user, chat))

    def test_workspace_admin_cannot_read_private(self):
        user = SimpleNamespace(id="admin")
        chat = SimpleNamespace(
            user_id="alice",
            organization_id="org",
            visibility=VISIBILITY_PRIVATE,
        )
        member = SimpleNamespace(role="admin")
        with patch(
            "open_webui.utils.organizations.Organizations.get_member",
            return_value=member,
        ):
            self.assertFalse(can_read_chat(user, chat))
            self.assertFalse(can_write_chat(user, chat))

    def test_member_can_read_org_shared_but_not_write(self):
        user = SimpleNamespace(id="bob")
        chat = SimpleNamespace(
            user_id="alice",
            organization_id="org",
            visibility=VISIBILITY_ORGANIZATION,
        )
        member = SimpleNamespace(role="user")
        with patch(
            "open_webui.utils.organizations.Organizations.get_member",
            return_value=member,
        ):
            self.assertTrue(can_read_chat(user, chat))
            self.assertFalse(can_write_chat(user, chat))

    def test_non_member_cannot_read_org_shared(self):
        user = SimpleNamespace(id="eve")
        chat = SimpleNamespace(
            user_id="alice",
            organization_id="org",
            visibility=VISIBILITY_ORGANIZATION,
        )
        with patch(
            "open_webui.utils.organizations.Organizations.get_member",
            return_value=None,
        ):
            self.assertFalse(can_read_chat(user, chat))


class OrgResourceAclTest(unittest.TestCase):
    def test_private_resource_is_creator_only(self):
        user = SimpleNamespace(id="bob")
        resource = SimpleNamespace(
            user_id="alice",
            organization_id="org",
            visibility=VISIBILITY_PRIVATE,
        )
        self.assertFalse(can_read_org_resource(user, resource))
        self.assertFalse(can_write_org_resource(user, resource))

    def test_org_shared_readable_by_members_writable_by_admins(self):
        member = SimpleNamespace(id="bob")
        admin = SimpleNamespace(id="carol")
        resource = SimpleNamespace(
            user_id="alice",
            organization_id="org",
            visibility=VISIBILITY_ORGANIZATION,
        )
        with patch(
            "open_webui.utils.organizations.is_member", return_value=True
        ), patch(
            "open_webui.utils.organizations.is_org_admin",
            side_effect=lambda org_id, user_id: user_id == "carol",
        ):
            self.assertTrue(can_read_org_resource(member, resource))
            self.assertFalse(can_write_org_resource(member, resource))
            self.assertTrue(can_write_org_resource(admin, resource))

    def test_platform_org_id_constant(self):
        self.assertEqual(PLATFORM_ORG_ID, "platform")
