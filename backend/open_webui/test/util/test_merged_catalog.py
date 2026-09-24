"""merged_catalog combines built-in tools and generated skill tools.

The chat loop and the endpoint both call it, so a tool name resolves to the same callable on both.
On a name collision, the skill tool replaces the built-in.
"""

import ast
import pathlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.utils import middleware
from open_webui.utils.tools import merged_catalog

USER = SimpleNamespace(id="account-1", role="user")

SKILL_TOOL = {"spec": {"name": "shared"}, "origin": "skill"}
BUILTIN_TOOL = {"spec": {"name": "shared"}, "origin": "builtin"}
OTHER_BUILTIN = {"spec": {"name": "only_builtin"}, "origin": "builtin"}


def patched(generated, builtins=None, builtin_error=None):
    generated_patch = patch(
        "open_webui.utils.tools.get_tools", return_value=generated
    )
    if builtin_error is not None:
        builtin_patch = patch(
            "open_webui.utils.builtin_tools.get_builtin_tools",
            side_effect=builtin_error,
        )
    else:
        builtin_patch = patch(
            "open_webui.utils.builtin_tools.get_builtin_tools",
            return_value=builtins or {},
        )
    return generated_patch, builtin_patch


class CollisionRuleTest(unittest.TestCase):
    def test_a_skill_tool_replaces_a_same_named_builtin(self):
        # Same precedence as the chat loop's previous {**builtins, **generated} merge.
        generated, builtins = patched(
            {"shared": SKILL_TOOL}, {"shared": BUILTIN_TOOL, "only_builtin": OTHER_BUILTIN}
        )
        with generated, builtins:
            catalog = merged_catalog(None, ["t1"], USER, {})
        self.assertEqual(catalog["shared"]["origin"], "skill")
        self.assertIn("only_builtin", catalog)

    def test_builtins_survive_when_nothing_collides(self):
        generated, builtins = patched(
            {"a_skill": SKILL_TOOL}, {"only_builtin": OTHER_BUILTIN}
        )
        with generated, builtins:
            catalog = merged_catalog(None, ["t1"], USER, {})
        self.assertEqual(sorted(catalog), ["a_skill", "only_builtin"])


class NoToolIdsTest(unittest.TestCase):
    def test_builtins_alone_when_no_tool_ids_are_asked_for(self):
        generated, builtins = patched({}, {"only_builtin": OTHER_BUILTIN})
        with generated, builtins as loader:
            catalog = merged_catalog(None, [], USER, {})
        self.assertEqual(sorted(catalog), ["only_builtin"])
        loader.assert_called_once()

    def test_the_generated_producer_is_not_called_for_an_empty_list(self):
        generated, builtins = patched({}, {})
        with generated as producer, builtins:
            merged_catalog(None, [], USER, {})
        producer.assert_not_called()


class BuiltinFailureTest(unittest.TestCase):
    def test_a_failing_builtin_loader_leaves_the_generated_tools(self):
        # The loader's exception is logged, and the generated tools are still returned.
        generated, builtins = patched(
            {"a_skill": SKILL_TOOL}, builtin_error=RuntimeError("boom")
        )
        with generated, builtins:
            catalog = merged_catalog(None, ["t1"], USER, {})
        self.assertEqual(sorted(catalog), ["a_skill"])

    def test_a_failing_builtin_loader_does_not_raise(self):
        generated, builtins = patched({}, builtin_error=RuntimeError("boom"))
        with generated, builtins:
            self.assertEqual(merged_catalog(None, [], USER, {}), {})


class OneMergeSiteTest(unittest.TestCase):
    def test_the_chat_loop_no_longer_merges_for_itself(self):
        source = pathlib.Path(middleware.__file__).read_text()
        names = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                names.update(alias.name for alias in node.names)
        self.assertNotIn(
            "get_builtin_tools",
            names,
            "middleware imports get_builtin_tools; the chat loop must use the shared catalog merge",
        )


if __name__ == "__main__":
    unittest.main()
