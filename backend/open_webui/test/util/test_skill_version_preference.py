"""Same-name skills keep the higher version when tools collide."""

from __future__ import annotations

import unittest

from open_webui.utils.skill_version import (
    newest_skill_per_name,
    parse_tool_version,
    prefer_incoming_tool_version,
    register_tool_by_function_name,
    resolve_tool_selection,
    tool_version_from_record,
)


class ParseToolVersionTest(unittest.TestCase):
    def test_numeric_order(self):
        self.assertTrue(parse_tool_version("0.2.0") > parse_tool_version("0.1.9"))
        self.assertTrue(parse_tool_version("1.0.0") > parse_tool_version("0.9.9"))
        self.assertTrue(parse_tool_version("v0.1.10") > parse_tool_version("0.1.9"))
        self.assertEqual(parse_tool_version("0.1"), parse_tool_version("0.1.0"))

    def test_prerelease_below_release(self):
        self.assertTrue(parse_tool_version("1.0.0") > parse_tool_version("1.0.0-rc1"))

    def test_missing(self):
        self.assertIsNone(parse_tool_version(None))
        self.assertIsNone(parse_tool_version(""))
        self.assertIsNone(parse_tool_version("not-a-version"))


class PreferIncomingVersionTest(unittest.TestCase):
    def test_higher_replaces(self):
        self.assertTrue(prefer_incoming_tool_version("0.2.0", "0.1.9"))

    def test_lower_does_not_replace(self):
        self.assertFalse(prefer_incoming_tool_version("0.1.0", "0.1.9"))

    def test_equal_keeps_existing(self):
        self.assertFalse(prefer_incoming_tool_version("0.1.9", "0.1.9"))

    def test_versioned_beats_missing(self):
        self.assertTrue(prefer_incoming_tool_version("0.1.0", None))
        self.assertFalse(prefer_incoming_tool_version(None, "0.1.0"))

    def test_both_missing_keeps_existing(self):
        self.assertFalse(prefer_incoming_tool_version(None, None))


class ToolVersionFromRecordTest(unittest.TestCase):
    def test_from_manifest(self):
        class Meta:
            manifest = {"kind": "skill", "version": "0.1.9"}

        class Tool:
            meta = Meta()

        self.assertEqual(tool_version_from_record(Tool()), "0.1.9")

    def test_missing(self):
        class Tool:
            meta = None

        self.assertIsNone(tool_version_from_record(Tool()))
        self.assertIsNone(tool_version_from_record(None))


class RegisterToolByFunctionNameTest(unittest.TestCase):
    def test_newer_skill_wins_regardless_of_order(self):
        tools = {}
        register_tool_by_function_name(
            tools, "plot", {"tool_id": "skill_plot_old", "version": "0.1.0"}
        )
        register_tool_by_function_name(
            tools, "plot", {"tool_id": "skill_plot_new", "version": "0.2.0"}
        )
        self.assertEqual(tools["plot"]["tool_id"], "skill_plot_new")

        tools = {}
        register_tool_by_function_name(
            tools, "plot", {"tool_id": "skill_plot_new", "version": "0.2.0"}
        )
        register_tool_by_function_name(
            tools, "plot", {"tool_id": "skill_plot_old", "version": "0.1.0"}
        )
        self.assertEqual(tools["plot"]["tool_id"], "skill_plot_new")

    def test_unversioned_loses_to_versioned(self):
        tools = {}
        register_tool_by_function_name(
            tools, "plot", {"tool_id": "skill_plot_plain", "version": None}
        )
        register_tool_by_function_name(
            tools, "plot", {"tool_id": "skill_plot_v", "version": "0.1.0"}
        )
        self.assertEqual(tools["plot"]["tool_id"], "skill_plot_v")


class ResolveToolSelectionTest(unittest.TestCase):
    def test_substitutes_higher_version_not_in_enabled_list(self):
        skills = [
            {"id": "skill_ecmwf_fetch", "skill_name": "ecmwf-fetch", "version": "0.1.12"},
            {
                "id": "skill_branch_ecmwf_fetch",
                "skill_name": "ecmwf-fetch",
                "version": "0.1.13",
            },
        ]
        resolved = resolve_tool_selection(["skill_ecmwf_fetch"], skills)
        self.assertEqual(resolved, ["skill_branch_ecmwf_fetch"])

    def test_equal_version_keeps_requested(self):
        skills = [
            {"id": "skill_plot", "skill_name": "plot", "version": "0.1.16"},
            {"id": "skill_branch_plot", "skill_name": "plot", "version": "0.1.16"},
        ]
        resolved = resolve_tool_selection(["skill_branch_plot"], skills)
        self.assertEqual(resolved, ["skill_branch_plot"])

    def test_dedupes_when_both_enabled(self):
        skills = [
            {"id": "skill_ecmwf_fetch", "skill_name": "ecmwf-fetch", "version": "0.1.12"},
            {
                "id": "skill_branch_ecmwf_fetch",
                "skill_name": "ecmwf-fetch",
                "version": "0.1.13",
            },
        ]
        resolved = resolve_tool_selection(
            ["skill_ecmwf_fetch", "skill_branch_ecmwf_fetch"], skills
        )
        self.assertEqual(resolved, ["skill_branch_ecmwf_fetch"])

    def test_names_become_the_newest_copy(self):
        skills = [
            {"id": "skill_plot", "skill_name": "plot", "version": "1.0.0"},
            {"id": "skill_pack_b_plot", "skill_name": "plot", "version": "1.0.1"},
            {"id": "skill_smap_fetch", "skill_name": "smap-fetch", "version": "0.3.0"},
        ]
        self.assertEqual(
            resolve_tool_selection(["plot", "smap-fetch", "skill_plot"], skills),
            ["skill_pack_b_plot", "skill_smap_fetch"],
        )

    def test_other_ids_and_unknown_names_pass_through(self):
        skills = [{"id": "skill_plot", "skill_name": "plot", "version": "1.0.0"}]
        self.assertEqual(
            resolve_tool_selection(["server:0", "gone", "plot"], skills),
            ["server:0", "gone", "skill_plot"],
        )


class NewestSkillPerNameTest(unittest.TestCase):
    def test_keeps_the_highest_version_and_the_first_on_a_tie(self):
        skills = [
            {"id": "a", "skill_name": "plot", "version": "1.0.0"},
            {"id": "b", "skill_name": "plot", "version": "1.0.0"},
            {"id": "c", "skill_name": "plot", "version": "0.9.0"},
            {"id": "d", "skill_name": "chirps-fetch", "version": "0.1.0"},
            {"id": "e", "skill_name": "", "version": "5.0.0"},
        ]
        newest = newest_skill_per_name(skills)
        self.assertEqual({k: v["id"] for k, v in newest.items()}, {"plot": "a", "chirps-fetch": "d"})