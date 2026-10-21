"""Active organization resolution is one lookup."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from open_webui.utils.organizations import (
    chat_organization_id,
    get_active_organization_id,
    request_organization_id,
)


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


class ChatOrganizationTest(unittest.TestCase):
    """A saved chat's messages run in the chat's organization."""

    def _user(self):
        return SimpleNamespace(id="alice")

    def _resolve(self, chat, org=None, member=None):
        with patch(
            "open_webui.utils.organizations.Organizations.get_organization_for_member",
            return_value=(org, member),
        ) as joined:
            result = chat_organization_id(chat, self._user(), "active")
        return result, joined

    def test_temporary_chat_keeps_active_organization(self):
        result, joined = self._resolve(None)
        self.assertEqual(result, "active")
        joined.assert_not_called()

    def test_chat_in_active_organization_needs_no_lookup(self):
        result, joined = self._resolve(SimpleNamespace(organization_id="active"))
        self.assertEqual(result, "active")
        joined.assert_not_called()

    def test_chat_from_another_organization_uses_that_organization(self):
        result, joined = self._resolve(
            SimpleNamespace(organization_id="team"),
            org=SimpleNamespace(id="team", active=True),
            member=SimpleNamespace(role="user"),
        )
        self.assertEqual(result, "team")
        joined.assert_called_once_with("team", "alice")

    def test_former_member_keeps_active_organization(self):
        result, _ = self._resolve(
            SimpleNamespace(organization_id="team"),
            org=SimpleNamespace(id="team", active=True),
            member=None,
        )
        self.assertEqual(result, "active")

    def test_inactive_chat_organization_keeps_active_organization(self):
        result, _ = self._resolve(
            SimpleNamespace(organization_id="team"),
            org=SimpleNamespace(id="team", active=False),
            member=SimpleNamespace(role="user"),
        )
        self.assertEqual(result, "active")


class RequestOrganizationTest(unittest.TestCase):
    """The request's organization comes from its metadata, then the header."""

    def _request(self, header=None, metadata=None):
        request = SimpleNamespace(headers={}, state=SimpleNamespace())
        if header is not None:
            request.headers["X-Organization-Id"] = header
        if metadata is not None:
            request.state.metadata = metadata
        return request

    def test_metadata_wins_over_header(self):
        request = self._request("other", {"organization_id": "team"})
        self.assertEqual(request_organization_id(request), "team")

    def test_metadata_without_header(self):
        request = self._request(metadata={"organization_id": "team"})
        self.assertEqual(request_organization_id(request), "team")

    def test_header_when_metadata_has_no_organization(self):
        request = self._request(" team ", {"organization_id": None})
        self.assertEqual(request_organization_id(request), "team")

    def test_nothing_set(self):
        self.assertIsNone(request_organization_id(self._request(" ")))


if __name__ == "__main__":
    unittest.main()
