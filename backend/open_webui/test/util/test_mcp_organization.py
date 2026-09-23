"""The organization an endpoint call runs in, named by the request's X-Organization-Id header.

A blank or absent header, or the account id, is the personal organization. A named organization
must exist, have the account as a member, and be active. The tests stub effective_user_role with a
fixed return value and check that call_organization_id passes it the caller and the resolved
organization and applies the returned role.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastmcp.exceptions import ToolError

from open_webui.mcp.organization import (
    active_organization_id,
    call_organization_id,
    requested_organization_id,
)

ACCOUNT = SimpleNamespace(id="account-1", role="user")
PERSONAL = SimpleNamespace(id=ACCOUNT.id, active=True)
TEAM = SimpleNamespace(id="org-1", active=True)
MEMBER = SimpleNamespace(role="user")


def organizations(personal=PERSONAL, joined=(TEAM, MEMBER)):
    ensure = patch(
        "open_webui.mcp.organization.Organizations.ensure_personal",
        return_value=personal,
    )
    lookup = patch(
        "open_webui.mcp.organization.Organizations.get_organization_for_member",
        return_value=joined,
    )
    return ensure, lookup


def headers(values):
    return patch("open_webui.mcp.organization.get_http_headers", return_value=values)


def effective_role(role="user"):
    return patch("open_webui.mcp.organization.effective_user_role", return_value=role)


def account(role="user"):
    return SimpleNamespace(id=ACCOUNT.id, role=role)


class HeaderTest(unittest.TestCase):
    def test_the_header_is_read_from_the_request(self):
        with headers({"x-organization-id": "org-1"}):
            self.assertEqual(requested_organization_id(), "org-1")

    def test_no_header_reads_as_none(self):
        with headers({}):
            self.assertIsNone(requested_organization_id())

    def test_the_call_runs_in_the_organization_the_header_names(self):
        ensure, lookup = organizations()
        with headers({"x-organization-id": "org-1"}), ensure, lookup as joined, effective_role():
            self.assertEqual(call_organization_id(account()), "org-1")
        joined.assert_called_once_with("org-1", ACCOUNT.id)

    def test_a_call_without_the_header_runs_in_the_personal_organization(self):
        ensure, lookup = organizations()
        with headers({}), ensure as personal, lookup as joined, effective_role():
            self.assertEqual(call_organization_id(account()), ACCOUNT.id)
        personal.assert_called_once_with(ACCOUNT.id)
        joined.assert_not_called()


class EffectiveRoleTest(unittest.TestCase):
    """effective_user_role is stubbed with a fixed return value. call_organization_id passes it the
    caller and the resolved organization and applies the returned role."""

    def call(self, caller, effective):
        ensure, lookup = organizations()
        with headers({"x-organization-id": "org-1"}), ensure, lookup, effective_role(
            effective
        ) as role:
            call_organization_id(caller)
        return role

    def test_the_returned_role_is_applied(self):
        caller = account(role="admin")
        role = self.call(caller, "user")
        self.assertEqual(caller.role, "user")
        role.assert_called_once()
        self.assertEqual(role.call_args.args, (caller, "org-1"))

    def test_the_effective_role_is_computed_for_the_resolved_organization(self):
        caller = account(role="admin")
        role = self.call(caller, "admin")
        self.assertEqual(role.call_args.args, (caller, "org-1"))
        self.assertEqual(caller.role, "admin")

    def test_a_refused_organization_leaves_the_role_unchanged(self):
        caller = account(role="admin")
        ensure, lookup = organizations(joined=(TEAM, None))
        with headers({"x-organization-id": "org-1"}), ensure, lookup, effective_role(
            "user"
        ) as role, self.assertRaises(ToolError):
            call_organization_id(caller)
        role.assert_not_called()
        self.assertEqual(caller.role, "admin")


class PersonalDefaultTest(unittest.TestCase):
    def resolve(self, requested):
        ensure, lookup = organizations()
        with ensure as personal, lookup as joined:
            result = active_organization_id(ACCOUNT, requested)
        personal.assert_called_once_with(ACCOUNT.id)
        joined.assert_not_called()
        return result

    def test_an_absent_header_is_the_personal_organization(self):
        self.assertEqual(self.resolve(None), ACCOUNT.id)

    def test_a_blank_header_is_the_personal_organization(self):
        self.assertEqual(self.resolve("   "), ACCOUNT.id)

    def test_the_account_id_is_the_personal_organization(self):
        self.assertEqual(self.resolve(ACCOUNT.id), ACCOUNT.id)

    def test_an_inactive_personal_organization_is_refused(self):
        ensure, lookup = organizations(personal=SimpleNamespace(id=ACCOUNT.id, active=False))
        with ensure, lookup, self.assertRaises(ToolError):
            active_organization_id(ACCOUNT, None)


class NamedOrganizationTest(unittest.TestCase):
    def resolve(self, joined, requested="org-1"):
        ensure, lookup = organizations(joined=joined)
        with ensure as personal, lookup:
            try:
                return active_organization_id(ACCOUNT, requested)
            finally:
                personal.assert_not_called()

    def test_a_member_of_an_active_organization_runs_in_it(self):
        self.assertEqual(self.resolve((TEAM, MEMBER)), "org-1")

    def test_surrounding_whitespace_is_ignored(self):
        self.assertEqual(self.resolve((TEAM, MEMBER), requested=" org-1 "), "org-1")

    def test_an_unknown_organization_is_refused(self):
        with self.assertRaises(ToolError):
            self.resolve((None, None))

    def test_a_non_member_is_refused(self):
        with self.assertRaises(ToolError):
            self.resolve((TEAM, None))

    def test_an_inactive_organization_is_refused(self):
        with self.assertRaises(ToolError):
            self.resolve((SimpleNamespace(id="org-1", active=False), MEMBER))


if __name__ == "__main__":
    unittest.main()
