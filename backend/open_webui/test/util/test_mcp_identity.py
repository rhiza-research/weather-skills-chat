"""Resolving a verified token to an account, and the cases that are refused.

The authorization server stores the approving user's id as each token's subject. There is no
lookup by email, because any account can claim an email address.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastmcp.exceptions import ToolError

from open_webui.mcp import identity
from open_webui.mcp.identity import resolve_caller

USER_ID = "8f1c0e64-1a2b-4c3d-9e8f-7a6b5c4d3e2f"
# Carries a role because resolution refuses accounts whose role the interface refuses.
ACCOUNT = SimpleNamespace(id=USER_ID, email="priya@example.com", role="user")


def token(subject):
    return SimpleNamespace(subject=subject, claims={})


class ResolveCallerTest(unittest.TestCase):
    def test_resolves_by_the_stored_user_id(self):
        with patch.object(
            identity, "get_access_token", return_value=token(USER_ID)
        ), patch.object(identity.Users, "get_user_by_id", return_value=ACCOUNT) as lookup:
            self.assertIs(resolve_caller(), ACCOUNT)
        lookup.assert_called_once_with(USER_ID)

    def test_refuses_when_no_token_reached_the_call(self):
        with patch.object(identity, "get_access_token", return_value=None):
            with self.assertRaises(ToolError):
                resolve_caller()

    def test_refuses_when_the_token_carries_no_subject(self):
        with patch.object(identity, "get_access_token", return_value=token(None)):
            with self.assertRaises(ToolError):
                resolve_caller()

    def test_refuses_when_the_account_is_gone(self):
        with patch.object(
            identity, "get_access_token", return_value=token(USER_ID)
        ), patch.object(identity.Users, "get_user_by_id", return_value=None):
            with self.assertRaises(ToolError):
                resolve_caller()

    def test_never_resolves_by_email(self):
        verified = SimpleNamespace(subject=None, claims={"email": ACCOUNT.email})
        with patch.object(identity, "get_access_token", return_value=verified), patch.object(
            identity.Users, "get_user_by_email", return_value=ACCOUNT
        ) as by_email:
            with self.assertRaises(ToolError):
                resolve_caller()
        by_email.assert_not_called()

    def test_creates_nothing(self):
        with patch.object(
            identity, "get_access_token", return_value=token(USER_ID)
        ), patch.object(identity.Users, "get_user_by_id", return_value=None), patch.object(
            identity.Users, "insert_new_user"
        ) as insert:
            with self.assertRaises(ToolError):
                resolve_caller()
        insert.assert_not_called()


class AccountStatusTest(unittest.TestCase):
    """The endpoint refuses accounts whose current role the interface refuses, such as pending.

    The role is read on every call, so an account demoted after approving a client is refused.
    """

    def _resolve(self, role):
        account = SimpleNamespace(id=USER_ID, role=role)
        with patch.object(
            identity, "get_access_token", return_value=token(USER_ID)
        ), patch.object(identity.Users, "get_user_by_id", return_value=account):
            return identity.resolve_caller()

    def test_a_user_is_admitted(self):
        self.assertEqual(self._resolve("user").role, "user")

    def test_an_admin_is_admitted(self):
        self.assertEqual(self._resolve("admin").role, "admin")

    def test_a_pending_account_is_refused(self):
        with self.assertRaises(ToolError) as raised:
            self._resolve("pending")
        self.assertIn("pending", str(raised.exception))

    def test_the_refusal_says_what_is_admitted(self):
        with self.assertRaises(ToolError) as raised:
            self._resolve("pending")
        for role in identity.ACTIVE_ROLES:
            self.assertIn(role, str(raised.exception))

    def test_an_unknown_role_is_refused(self):
        with self.assertRaises(ToolError):
            self._resolve("something-else")

    def test_the_admitted_set_matches_what_the_interface_admits(self):
        # The interface defines this set in a module the endpoint does not import, so the value is
        # checked here.
        self.assertEqual(identity.ACTIVE_ROLES, frozenset({"user", "admin"}))


if __name__ == "__main__":
    unittest.main()
