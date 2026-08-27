"""Private tools/skills stay owner-only — no admin bypass."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from open_webui.utils.access_control import has_access, user_owns_or_has_access


class UserOwnsOrHasAccessTest(unittest.TestCase):
    def test_owner_always_has_access(self):
        self.assertTrue(
            user_owns_or_has_access("alice", "alice", {}, "read")
        )
        self.assertTrue(
            user_owns_or_has_access("alice", "alice", {}, "write")
        )

    def test_private_blocks_non_owner_including_when_called_for_admin_id(self):
        # Empty ACL = private; non-owners denied regardless of role.
        self.assertFalse(
            user_owns_or_has_access("admin-user", "alice", {}, "read")
        )
        self.assertFalse(
            user_owns_or_has_access("admin-user", "alice", {}, "write")
        )

    def test_public_grants_read_to_everyone(self):
        self.assertTrue(
            user_owns_or_has_access("bob", "alice", None, "read")
        )
        self.assertFalse(
            user_owns_or_has_access("bob", "alice", None, "write")
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

    def test_has_access_private_is_false(self):
        with patch(
            "open_webui.models.groups.Groups.get_groups_by_member_id",
            return_value=[],
        ), patch(
            "open_webui.models.teams.Teams.user_team_ids",
            return_value=[],
        ):
            self.assertFalse(has_access("anyone", "read", {}))


if __name__ == "__main__":
    unittest.main()
