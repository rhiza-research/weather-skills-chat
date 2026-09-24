"""Resolving a verified token to an account, and the cases that are refused.

The lookup key must match the one the interface's sign-in writes. There is no fallback to email,
because any account can claim an email address.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastmcp.exceptions import ToolError

from open_webui.mcp import identity
from open_webui.mcp.identity import (
    DEFAULT_SUBJECT_CLAIM,
    PROVIDER_REGISTRATION_NAME,
    account_key,
    resolve_caller,
    subject_claim,
)

SUBJECT = "8f1c0e64-1a2b-4c3d-9e8f-7a6b5c4d3e2f"
# Carries a role because resolution refuses accounts whose role the interface refuses.
ACCOUNT = SimpleNamespace(id="account-1", email="priya@example.com", role="user")


def token(claims):
    return SimpleNamespace(claims=claims)


class AccountKeyTest(unittest.TestCase):
    def test_key_is_the_provider_name_then_the_subject(self):
        # utils/oauth.py stores f"{provider}@{sub}" when it links an account.
        self.assertEqual(account_key(SUBJECT), f"{PROVIDER_REGISTRATION_NAME}@{SUBJECT}")

    def test_the_raw_subject_is_not_the_key(self):
        self.assertNotEqual(account_key(SUBJECT), SUBJECT)


class SubjectClaimTest(unittest.TestCase):
    def test_defaults_to_the_standard_claim(self):
        with patch.dict("open_webui.mcp.identity.OAUTH_PROVIDERS", {}, clear=True):
            self.assertEqual(subject_claim(), DEFAULT_SUBJECT_CLAIM)

    def test_a_registration_override_is_honored(self):
        with patch.dict(
            "open_webui.mcp.identity.OAUTH_PROVIDERS",
            {PROVIDER_REGISTRATION_NAME: {"sub_claim": "oid"}},
            clear=True,
        ):
            self.assertEqual(subject_claim(), "oid")


class ResolveCallerTest(unittest.TestCase):
    def test_resolves_by_the_prefixed_key(self):
        with patch(
            "open_webui.mcp.identity.get_access_token",
            return_value=token({DEFAULT_SUBJECT_CLAIM: SUBJECT}),
        ), patch(
            "open_webui.mcp.identity.Users.get_user_by_oauth_sub",
            return_value=ACCOUNT,
        ) as lookup:
            self.assertIs(resolve_caller(), ACCOUNT)
        lookup.assert_called_once_with(f"{PROVIDER_REGISTRATION_NAME}@{SUBJECT}")

    def test_refuses_when_no_token_reached_the_call(self):
        with patch("open_webui.mcp.identity.get_access_token", return_value=None):
            with self.assertRaises(ToolError):
                resolve_caller()

    def test_refuses_when_the_token_carries_no_subject(self):
        with patch(
            "open_webui.mcp.identity.get_access_token", return_value=token({})
        ):
            with self.assertRaises(ToolError) as raised:
                resolve_caller()
            self.assertIn(DEFAULT_SUBJECT_CLAIM, str(raised.exception))

    def test_refuses_when_no_account_is_linked(self):
        with patch(
            "open_webui.mcp.identity.get_access_token",
            return_value=token({DEFAULT_SUBJECT_CLAIM: SUBJECT}),
        ), patch(
            "open_webui.mcp.identity.Users.get_user_by_oauth_sub", return_value=None
        ):
            with self.assertRaises(ToolError):
                resolve_caller()

    def test_never_resolves_by_email(self):
        # A token with an email claim and no subject is refused.
        with patch(
            "open_webui.mcp.identity.get_access_token",
            return_value=token({"email": ACCOUNT.email}),
        ), patch(
            "open_webui.mcp.identity.Users.get_user_by_oauth_sub", return_value=None
        ) as lookup:
            with self.assertRaises(ToolError):
                resolve_caller()
        lookup.assert_not_called()

    def test_creates_nothing_when_no_account_is_linked(self):
        with patch(
            "open_webui.mcp.identity.get_access_token",
            return_value=token({DEFAULT_SUBJECT_CLAIM: SUBJECT}),
        ), patch(
            "open_webui.mcp.identity.Users.get_user_by_oauth_sub", return_value=None
        ), patch(
            "open_webui.mcp.identity.Users.insert_new_user"
        ) as insert:
            with self.assertRaises(ToolError):
                resolve_caller()
        insert.assert_not_called()


class AccountStatusTest(unittest.TestCase):
    """The endpoint refuses accounts whose role the interface refuses, such as pending.

    A valid token shows the provider knows the person. The account's role decides whether this
    service admits them.
    """

    def _resolve(self, role):
        account = SimpleNamespace(
            id="an-account", role=role, oauth_sub="oidc@a-subject"
        )
        verified = SimpleNamespace(claims={"sub": "a-subject"})
        with patch.object(
            identity, "get_access_token", return_value=verified
        ), patch.object(identity.Users, "get_user_by_oauth_sub", return_value=account):
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
