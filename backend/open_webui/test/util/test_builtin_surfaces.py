"""Which built-in tools the endpoint publishes, checked against the real built-in catalog.

Each name is listed explicitly. A new built-in published to the endpoint fails
test_only_the_expected_builtins_go_outward until it is added here.
"""

import unittest

from open_webui.utils.builtin_tools import get_builtin_tools
from open_webui.utils.tool_surfaces import Surface, publishes_to

# Tools that write to the account: schedule automations, save preferences, publish share links,
# create folders, copy files, and send email. None are published to the endpoint.
ACCOUNT_WRITING = (
    "create_automation",
    "create_preference",
    "create_zarr_view",
    "copy_intermediate_result",
    "create_folder",
    "send_email",
)

# Read-only tools that are not published to the endpoint:
# - list_available_tools describes other tools, including ones the endpoint does not publish.
# - list_email_recipients returns organization rosters.
# - secrets_page and list_preferences return instructions for the chat model to give the user in
#   the interface.
# - display_image: the endpoint serves images through get_artifact.
READS_BUT_WITHHELD = (
    "list_available_tools",
    "list_email_recipients",
    "secrets_page",
    "list_preferences",
    "display_image",
)

PUBLISHED_OUTWARD = ("list_artifacts",)

CODE_INTERPRETER_ENABLED = {"__metadata__": {"features": {"code_interpreter": True}}}


class BuiltinSurfaceTest(unittest.TestCase):
    def setUp(self):
        self.catalog = get_builtin_tools(CODE_INTERPRETER_ENABLED)

    def published(self, name):
        return publishes_to(name, self.catalog[name], Surface.ENDPOINT)

    def test_every_expected_builtin_is_present(self):
        # A renamed or removed tool would otherwise pass the assertions below without being checked.
        for name in (
            *ACCOUNT_WRITING,
            *READS_BUT_WITHHELD,
            *PUBLISHED_OUTWARD,
            "execute_code",
        ):
            self.assertIn(name, self.catalog)

    def test_no_account_writing_tool_is_published_outward(self):
        for name in ACCOUNT_WRITING:
            self.assertFalse(self.published(name), name)

    def test_the_code_interpreter_is_not_published_outward(self):
        # It executes code, and it asks the caller a question mid-run, which the endpoint cannot relay.
        self.assertFalse(self.published("execute_code"))

    def test_the_withheld_readers_are_not_published_outward(self):
        for name in READS_BUT_WITHHELD:
            self.assertFalse(self.published(name), name)

    def test_the_artifact_listing_is_published_outward(self):
        for name in PUBLISHED_OUTWARD:
            self.assertTrue(self.published(name), name)

    def test_exactly_one_builtin_goes_outward(self):
        outward = sorted(
            name for name in self.catalog if self.published(name)
        )
        self.assertEqual(outward, list(PUBLISHED_OUTWARD))

    def test_every_builtin_is_published_to_the_interface(self):
        # Every built-in is published to the interface.
        for name in self.catalog:
            self.assertTrue(
                publishes_to(name, self.catalog[name], Surface.INTERFACE), name
            )

    def test_every_builtin_states_its_surfaces(self):
        for name, entry in self.catalog.items():
            self.assertIn("surfaces", entry, name)


class CodeInterpreterOffTest(unittest.TestCase):
    def test_the_code_interpreter_is_absent_without_the_feature(self):
        self.assertNotIn("execute_code", get_builtin_tools({}))


if __name__ == "__main__":
    unittest.main()
