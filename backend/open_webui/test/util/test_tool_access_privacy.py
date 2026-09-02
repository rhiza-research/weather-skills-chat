"""Unified workspace ACL — private stays private; admins get public/shared access."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from open_webui.utils.access_control import (
    can_update_access_control,
    has_access,
    user_owns_or_has_access,
)


class UserOwnsOrHasAccessTest(unittest.TestCase):
    def test_owner_always_has_access(self):
        self.assertTrue(
            user_owns_or_has_access("alice", "alice", {}, "read")
        )
        self.assertTrue(
            user_owns_or_has_access("alice", "alice", {}, "write")
        )

    def test_private_blocks_non_owner_including_admin(self):
        self.assertFalse(
            user_owns_or_has_access("admin-user", "alice", {}, "read", "admin")
        )
        self.assertFalse(
            user_owns_or_has_access("admin-user", "alice", {}, "write", "admin")
        )

    def test_public_grants_read_to_everyone_write_to_owner_and_admin(self):
        self.assertTrue(
            user_owns_or_has_access("bob", "alice", None, "read")
        )
        self.assertFalse(
            user_owns_or_has_access("bob", "alice", None, "write")
        )
        self.assertTrue(
            user_owns_or_has_access("admin-user", "alice", None, "read", "admin")
        )
        self.assertTrue(
            user_owns_or_has_access("admin-user", "alice", None, "write", "admin")
        )

    def test_explicit_user_grant(self):
        acl = {"read": {"user_ids": ["bob"]}, "write": {"user_ids": []}}
        with patch(
            "open_webui.models.groups.Groups.get_groups_by_member_id",
            return_value=[],
        ), patch(
            "open_webui.models.teams.Teams.user_team_ids",
            return_value=[],
        ):
            self.assertTrue(user_owns_or_has_access("bob", "alice", acl, "read"))
            self.assertFalse(user_owns_or_has_access("carol", "alice", acl, "read"))

    def test_admin_read_on_explicit_grant_without_write(self):
        acl = {"read": {"user_ids": ["admin-user"]}, "write": {"user_ids": []}}
        with patch(
            "open_webui.models.groups.Groups.get_groups_by_member_id",
            return_value=[],
        ), patch(
            "open_webui.models.teams.Teams.user_team_ids",
            return_value=[],
        ):
            self.assertTrue(
                user_owns_or_has_access("admin-user", "alice", acl, "read", "admin")
            )
            self.assertFalse(
                user_owns_or_has_access("admin-user", "alice", acl, "write", "admin")
            )

    def test_admin_write_on_explicit_write_grant(self):
        acl = {"write": {"user_ids": ["admin-user"]}}
        with patch(
            "open_webui.models.groups.Groups.get_groups_by_member_id",
            return_value=[],
        ), patch(
            "open_webui.models.teams.Teams.user_team_ids",
            return_value=[],
        ):
            self.assertTrue(
                user_owns_or_has_access("admin-user", "alice", acl, "write", "admin")
            )

    def test_has_access_private_is_false(self):
        with patch(
            "open_webui.models.groups.Groups.get_groups_by_member_id",
            return_value=[],
        ), patch(
            "open_webui.models.teams.Teams.user_team_ids",
            return_value=[],
        ):
            self.assertFalse(has_access("anyone", "read", {}))


class CanUpdateAccessControlTest(unittest.TestCase):
    def test_owner_can_privatize_without_sharing_permission(self):
        with patch(
            "open_webui.utils.access_control.has_permission",
            return_value=False,
        ):
            self.assertTrue(
                can_update_access_control(
                    "alice",
                    "user",
                    "alice",
                    None,
                    {},
                    "sharing.public_models",
                    {},
                )
            )

    def test_owner_cannot_make_public_without_sharing_permission(self):
        with patch(
            "open_webui.utils.access_control.has_permission",
            return_value=False,
        ):
            self.assertFalse(
                can_update_access_control(
                    "alice",
                    "user",
                    "alice",
                    {},
                    None,
                    "sharing.public_models",
                    {},
                )
            )

    def test_admin_can_make_public_resource_more_open(self):
        self.assertTrue(
            can_update_access_control(
                "admin-user",
                "admin",
                "alice",
                None,
                {"read": {"group_ids": ["g1"]}},
                "sharing.public_models",
                {},
            )
        )


if __name__ == "__main__":
    unittest.main()
