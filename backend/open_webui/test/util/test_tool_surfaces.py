"""Every catalog producer states which surfaces publish its entries.

An entry without the surfaces key is published nowhere, so these tests check that every producer
writes the key.
"""

import ast
import pathlib
import unittest
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.mcp import catalog as mcp_catalog
from open_webui.utils import builtin_tools, middleware, tools
from open_webui.utils.tool_surfaces import (
    BOTH_SURFACES,
    ENDPOINT_ONLY,
    INTERFACE_ONLY,
    SURFACES_KEY,
    Surface,
    published_to,
    publishes_to,
    surfaces_for_tool_record,
)

# Every module that builds a catalog entry.
PRODUCER_MODULES = (tools, builtin_tools, middleware)

ENTRY_MARKER_KEYS = ("callable", "spec")


def entry_literals(source):
    """Every dict literal in a module with a "spec" key, which marks a catalog entry."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Dict):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        # A `{**spread}` entry puts None in the key list.
        names = {
            ast.unparse(k)
            for k in node.keys
            if k is not None and not isinstance(k, ast.Constant)
        }
        if "spec" in keys:
            found.append((keys, names))
    return found


class ProducerCoverageTest(unittest.TestCase):
    def test_there_are_entries_to_check(self):
        # Guards against the matcher finding nothing, which would pass the next test trivially.
        total = sum(
            len(entry_literals(pathlib.Path(m.__file__).read_text()))
            for m in PRODUCER_MODULES
        )
        self.assertGreaterEqual(total, 4, "expected every known producer site")

    def test_every_entry_literal_states_its_surfaces(self):
        for module in PRODUCER_MODULES:
            path = pathlib.Path(module.__file__)
            for keys, names in entry_literals(path.read_text()):
                stated = SURFACES_KEY in keys or any(
                    SURFACES_KEY.upper() in name for name in names
                )
                self.assertTrue(
                    stated,
                    f"{path.name} builds an entry with keys {sorted(keys)} and no surfaces",
                )


class MissingKeyTest(unittest.TestCase):
    def test_a_missing_key_publishes_nowhere(self):
        # Returns False instead of raising, so the entry is withheld from both surfaces.
        self.assertFalse(publishes_to("nameless", {"spec": {}}, Surface.ENDPOINT))
        self.assertFalse(publishes_to("nameless", {"spec": {}}, Surface.INTERFACE))


class SurfaceMeaningTest(unittest.TestCase):
    def test_interface_only_is_not_published_to_the_endpoint(self):
        entry = {SURFACES_KEY: INTERFACE_ONLY}
        self.assertTrue(publishes_to("t", entry, Surface.INTERFACE))
        self.assertFalse(publishes_to("t", entry, Surface.ENDPOINT))

    def test_endpoint_only_is_not_published_to_the_interface(self):
        entry = {SURFACES_KEY: ENDPOINT_ONLY}
        self.assertFalse(publishes_to("t", entry, Surface.INTERFACE))
        self.assertTrue(publishes_to("t", entry, Surface.ENDPOINT))

    def test_both_is_published_to_both(self):
        entry = {SURFACES_KEY: BOTH_SURFACES}
        self.assertTrue(publishes_to("t", entry, Surface.INTERFACE))
        self.assertTrue(publishes_to("t", entry, Surface.ENDPOINT))

    def test_filtering_keeps_the_keys_it_arrived_with(self):
        catalog = {
            "a": {SURFACES_KEY: BOTH_SURFACES},
            "b": {SURFACES_KEY: INTERFACE_ONLY},
            "c": {SURFACES_KEY: ENDPOINT_ONLY},
        }
        self.assertEqual(
            sorted(published_to(catalog, Surface.ENDPOINT)), ["a", "c"]
        )
        self.assertEqual(
            sorted(published_to(catalog, Surface.INTERFACE)), ["a", "b"]
        )


class ConsumersHonorTheMarkingTest(unittest.TestCase):
    """The interface and endpoint accessors each filter the catalog by their surface."""

    CATALOG = {
        "shared": {SURFACES_KEY: BOTH_SURFACES, "spec": {"name": "shared"}},
        "interface_only": {SURFACES_KEY: INTERFACE_ONLY, "spec": {"name": "i"}},
        "endpoint_only": {SURFACES_KEY: ENDPOINT_ONLY, "spec": {"name": "e"}},
    }

    @contextmanager
    def merged(self):
        with patch.object(tools, "merged_catalog", return_value=dict(self.CATALOG)):
            yield

    def test_the_interface_accessor_withholds_an_endpoint_only_tool(self):
        with self.merged():
            got = tools.interface_catalog(None, [], None, {})
        self.assertEqual(sorted(got), ["interface_only", "shared"])

    def test_the_endpoint_accessor_withholds_an_interface_only_tool(self):
        with ExitStack() as stack:
            for name, value in (
                ("core_request", None),
                ("endpoint_tool_ids", []),
                ("merged_catalog", dict(self.CATALOG)),
            ):
                stack.enter_context(patch.object(mcp_catalog, name, return_value=value))
            stack.enter_context(
                patch.object(mcp_catalog.Tools, "get_tool_catalog", return_value=[])
            )
            got = mcp_catalog.endpoint_catalog(None, None, "org-1", {})
        self.assertEqual(sorted(got), ["endpoint_only", "shared"])

    def test_the_chat_loop_reads_the_filtered_accessor(self):
        # Checks the name bound in middleware, which is what the chat loop calls.
        self.assertIs(middleware.interface_catalog, tools.interface_catalog)
        self.assertFalse(hasattr(middleware, "merged_catalog"))


class ToolRecordTest(unittest.TestCase):
    def record(self, manifest):
        return SimpleNamespace(meta=SimpleNamespace(manifest=manifest))

    def test_a_skill_goes_to_both_surfaces(self):
        self.assertEqual(
            surfaces_for_tool_record(self.record({"kind": "skill"})), BOTH_SURFACES
        )

    def test_a_workspace_tool_stays_on_the_interface(self):
        self.assertEqual(
            surfaces_for_tool_record(self.record({"kind": "tool"})), INTERFACE_ONLY
        )

    def test_no_manifest_stays_on_the_interface(self):
        self.assertEqual(
            surfaces_for_tool_record(self.record(None)), INTERFACE_ONLY
        )

    def test_no_meta_at_all_stays_on_the_interface(self):
        self.assertEqual(
            surfaces_for_tool_record(SimpleNamespace(meta=None)), INTERFACE_ONLY
        )


if __name__ == "__main__":
    unittest.main()
