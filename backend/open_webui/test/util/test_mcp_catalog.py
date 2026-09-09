"""Which catalog entries the endpoint publishes.

The endpoint uses the default tool set automations use in the call's organization, limited to tools
published to the endpoint, and publishes the entries whose surfaces marking includes the endpoint.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.mcp.catalog import endpoint_catalog, endpoint_tool_ids
from open_webui.mcp.request import ORGANIZATION_HEADER
from open_webui.utils.tool_surfaces import (
    BOTH_SURFACES,
    ENDPOINT_ONLY,
    INTERFACE_ONLY,
    SURFACES_KEY,
)
from open_webui.utils.tools import accessible_tool_ids

USER = SimpleNamespace(id="account-1", role="user")
APP = SimpleNamespace(state=SimpleNamespace(TOOLS={}))
ORG = "org-1"


def row(tool_id, manifest, user_id="account-1", access_control=None):
    return SimpleNamespace(
        id=tool_id,
        user_id=user_id,
        access_control=access_control,
        meta=SimpleNamespace(manifest=manifest),
    )


CATALOG = [
    row("t-enabled", {"kind": "skill", "skill_name": "rain"}),
    # Not enabled in the organization, so accessible_skill_records leaves it out.
    row("t-not-enabled", {"kind": "skill", "skill_name": "wind"}),
    # A workspace tool is readable by its owner. access_control None is public read.
    row("t-workspace", {"kind": "tool"}),
    row("t-shared-workspace", {"kind": "tool"}, user_id="someone-else"),
    # access_control {} is owner-only.
    row(
        "t-private-workspace",
        {"kind": "tool"},
        user_id="someone-else",
        access_control={},
    ),
]

# The skills the organization enables, as accessible_skill_records returns them.
ENABLED_SKILLS = [
    {"id": "t-enabled", "skill_name": "rain", "version": None, "enabled": True}
]


def enabled_skills():
    return patch(
        "open_webui.utils.tools.accessible_skill_records", return_value=ENABLED_SKILLS
    )


class DefaultToolSetTest(unittest.TestCase):
    def ids(self):
        with enabled_skills() as records:
            ids = accessible_tool_ids(USER, ORG, catalog=CATALOG)
        return ids, records

    def test_a_skill_the_organization_enables_is_included(self):
        ids, _ = self.ids()
        self.assertIn("t-enabled", ids)

    def test_a_skill_the_organization_does_not_enable_is_excluded(self):
        ids, _ = self.ids()
        self.assertNotIn("t-not-enabled", ids)

    def test_the_organization_and_catalog_are_passed_to_the_skill_lookup(self):
        _, records = self.ids()
        self.assertEqual(records.call_args.args[1], ORG)
        self.assertIs(records.call_args.kwargs["catalog"], CATALOG)

    def test_the_default_set_includes_readable_workspace_tools(self):
        # accessible_tool_ids is the automation default; it is not limited to skills.
        ids, _ = self.ids()
        self.assertIn("t-workspace", ids)
        self.assertIn("t-shared-workspace", ids)

    def test_a_private_workspace_tool_owned_by_another_account_is_excluded(self):
        ids, _ = self.ids()
        self.assertNotIn("t-private-workspace", ids)


class EndpointToolIdsTest(unittest.TestCase):
    def ids(self, catalog=CATALOG):
        with enabled_skills():
            return endpoint_tool_ids(USER, ORG, catalog)

    def test_a_skill_the_organization_enables_is_included(self):
        self.assertIn("t-enabled", self.ids())

    def test_a_skill_the_organization_does_not_enable_is_excluded(self):
        self.assertNotIn("t-not-enabled", self.ids())

    def test_a_workspace_tool_is_excluded_before_it_is_loaded(self):
        # Workspace tools are published to the interface only.
        self.assertNotIn("t-workspace", self.ids())
        self.assertNotIn("t-shared-workspace", self.ids())

    def test_an_empty_catalog_gives_nothing(self):
        self.assertEqual(self.ids([]), [])


class EndpointCatalogTest(unittest.TestCase):
    def catalog(self, entries):
        with patch(
            "open_webui.mcp.catalog.Tools.get_tool_catalog", return_value=CATALOG
        ) as read, patch(
            "open_webui.mcp.catalog.merged_catalog", return_value=entries
        ) as merge, enabled_skills():
            result = endpoint_catalog(APP, USER, ORG, {})
        return result, merge, read

    def test_only_marked_entries_are_published(self):
        entries = {
            "a_skill": {SURFACES_KEY: BOTH_SURFACES},
            "an_interface_tool": {SURFACES_KEY: INTERFACE_ONLY},
            "an_endpoint_tool": {SURFACES_KEY: ENDPOINT_ONLY},
        }
        published, _, _ = self.catalog(entries)
        self.assertEqual(sorted(published), ["a_skill", "an_endpoint_tool"])

    def test_an_unmarked_entry_is_not_published(self):
        published, _, _ = self.catalog({"forgotten": {"spec": {}}})
        self.assertEqual(published, {})

    def test_a_skill_the_organization_does_not_enable_never_reaches_the_core(self):
        _, merge, _ = self.catalog({})
        passed_ids = merge.call_args.args[1]
        self.assertNotIn("t-not-enabled", passed_ids)
        self.assertIn("t-enabled", passed_ids)

    def test_the_catalog_is_read_once_and_passed_to_the_core(self):
        _, merge, read = self.catalog({})
        read.assert_called_once_with()
        self.assertIs(merge.call_args.kwargs["catalog"], CATALOG)

    def test_the_core_is_given_a_fabricated_request_carrying_the_app(self):
        _, merge, _ = self.catalog({})
        request = merge.call_args.args[0]
        self.assertIs(request.scope["app"], APP)

    def test_the_fabricated_request_names_the_organization(self):
        # get_tools reads the organization from this header when it resolves skill versions.
        _, merge, _ = self.catalog({})
        request = merge.call_args.args[0]
        self.assertEqual(request.headers.get(ORGANIZATION_HEADER), ORG)


if __name__ == "__main__":
    unittest.main()
