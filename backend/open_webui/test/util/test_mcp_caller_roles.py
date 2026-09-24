"""The roles the endpoint admits are the roles the interface admits.

The interface defines its set in a module the endpoint does not import, so the value is checked
here.
"""

import unittest

from open_webui.mcp import identity


class ActiveRolesTest(unittest.TestCase):
    def test_the_admitted_set_matches_what_the_interface_admits(self):
        self.assertEqual(identity.ACTIVE_ROLES, frozenset({"user", "admin"}))

    def test_the_refusal_names_the_role_and_what_is_admitted(self):
        message = identity.INACTIVE_ACCOUNT_MESSAGE.format(
            role="pending", active=", ".join(sorted(identity.ACTIVE_ROLES))
        )
        self.assertIn("pending", message)
        for role in identity.ACTIVE_ROLES:
            self.assertIn(role, message)


if __name__ == "__main__":
    unittest.main()
