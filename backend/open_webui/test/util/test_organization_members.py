"""Admin organization list loads members in one query."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.routers.organizations import _with_all_members


class OrganizationMemberBatchTest(unittest.TestCase):
    def test_all_orgs_share_one_member_lookup(self):
        orgs = [SimpleNamespace(id="a"), SimpleNamespace(id="b")]
        members = {
            "a": [SimpleNamespace(user_id="admin", role="owner")],
            "b": [SimpleNamespace(user_id="other", role="user")],
        }
        with patch(
            "open_webui.routers.organizations.Organizations.get_members"
        ) as per_org, patch(
            "open_webui.routers.organizations.Organizations.get_member"
        ) as one_member, patch(
            "open_webui.routers.organizations.Organizations.get_members_by_organization_ids",
            return_value=members,
        ) as batched:
            result = _with_all_members(orgs, "admin")

        batched.assert_called_once_with(["a", "b"])
        per_org.assert_not_called()
        one_member.assert_not_called()
        self.assertEqual(result[0].role, "owner")
        self.assertEqual(result[0].members, members["a"])
        self.assertIsNone(result[1].role)


if __name__ == "__main__":
    unittest.main()
