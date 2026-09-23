"""Active organization resolution is one lookup."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from open_webui.utils.organizations import get_active_organization_id


class ActiveOrganizationTest(unittest.TestCase):
    def _user(self):
        return SimpleNamespace(id="alice")

    def test_personal_header_uses_ensure_personal_only(self):
        org = SimpleNamespace(id="alice", active=True)
        with patch(
            "open_webui.utils.organizations.Organizations.ensure_personal",
            return_value=org,
        ) as ensure, patch(
            "open_webui.utils.organizations.Organizations.get_organization_by_id"
        ) as by_id, patch(
            "open_webui.utils.organizations.Organizations.get_member"
        ) as member, patch(
            "open_webui.utils.organizations.Organizations.get_organization_for_member"
        ) as joined:
            result = get_active_organization_id(
                x_organization_id="alice", user=self._user()
            )
        self.assertEqual(result, "alice")
        ensure.assert_called_once_with("alice")
        by_id.assert_not_called()
        member.assert_not_called()
        joined.assert_not_called()

    def test_blank_header_uses_personal_org(self):
        org = SimpleNamespace(id="alice", active=True)
        with patch(
            "open_webui.utils.organizations.Organizations.ensure_personal",
            return_value=org,
        ) as ensure, patch(
            "open_webui.utils.organizations.Organizations.get_organization_for_member"
        ) as joined:
            result = get_active_organization_id(
                x_organization_id="  ", user=self._user()
            )
        self.assertEqual(result, "alice")
        ensure.assert_called_once_with("alice")
        joined.assert_not_called()

    def test_team_org_is_one_join(self):
        org = SimpleNamespace(id="team", active=True)
        member = SimpleNamespace(role="user")
        with patch(
            "open_webui.utils.organizations.Organizations.ensure_personal"
        ) as ensure, patch(
            "open_webui.utils.organizations.Organizations.get_organization_by_id"
        ) as by_id, patch(
            "open_webui.utils.organizations.Organizations.get_member"
        ) as get_member, patch(
            "open_webui.utils.organizations.Organizations.get_organization_for_member",
            return_value=(org, member),
        ) as joined:
            result = get_active_organization_id(
                x_organization_id="team", user=self._user()
            )
        self.assertEqual(result, "team")
        ensure.assert_not_called()
        by_id.assert_not_called()
        get_member.assert_not_called()
        joined.assert_called_once_with("team", "alice")

    def test_missing_org_is_not_found(self):
        with patch(
            "open_webui.utils.organizations.Organizations.get_organization_for_member",
            return_value=(None, None),
        ):
            with self.assertRaises(HTTPException) as caught:
                get_active_organization_id(
                    x_organization_id="missing", user=self._user()
                )
        self.assertEqual(caught.exception.status_code, 404)

    def test_non_member_is_forbidden(self):
        org = SimpleNamespace(id="team", active=True)
        with patch(
            "open_webui.utils.organizations.Organizations.get_organization_for_member",
            return_value=(org, None),
        ):
            with self.assertRaises(HTTPException) as caught:
                get_active_organization_id(
                    x_organization_id="team", user=self._user()
                )
        self.assertEqual(caught.exception.status_code, 403)

    def test_inactive_org_is_forbidden(self):
        org = SimpleNamespace(id="team", active=False)
        member = SimpleNamespace(role="user")
        with patch(
            "open_webui.utils.organizations.Organizations.get_organization_for_member",
            return_value=(org, member),
        ):
            with self.assertRaises(HTTPException) as caught:
                get_active_organization_id(
                    x_organization_id="team", user=self._user()
                )
        self.assertEqual(caught.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
