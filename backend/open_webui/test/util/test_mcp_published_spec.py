"""inject_depends_on_spec returns a copy and leaves its input spec unchanged.

The chat loop adds a depends_on parameter for its own scheduler. Skill wrappers do not accept it, so
a client that passed it would get a TypeError. Built-in entries reference module-level spec
constants, so modifying the input in place would add the parameter to those constants for every
later reader, including the endpoint.
"""

import unittest

from open_webui.utils.builtin_tools import LIST_ARTIFACTS_SPEC
from open_webui.utils.tool_parallel import (
    DEPENDS_ON_PARAM,
    inject_depends_on_spec,
)


def properties(spec):
    return (spec.get("parameters") or {}).get("properties") or {}


class InjectionDoesNotMutateTest(unittest.TestCase):
    def test_the_source_spec_is_left_alone(self):
        spec = {"name": "t", "parameters": {"properties": {"a": {"type": "string"}}}}
        inject_depends_on_spec(spec)
        self.assertNotIn(DEPENDS_ON_PARAM, properties(spec))

    def test_the_returned_spec_carries_the_parameter(self):
        spec = {"name": "t", "parameters": {"properties": {}}}
        self.assertIn(DEPENDS_ON_PARAM, properties(inject_depends_on_spec(spec)))

    def test_a_shared_module_constant_survives_injection(self):
        # An in-place injection here would make the endpoint advertise depends_on on list_artifacts.
        inject_depends_on_spec(LIST_ARTIFACTS_SPEC)
        inject_depends_on_spec(LIST_ARTIFACTS_SPEC)
        self.assertNotIn(DEPENDS_ON_PARAM, properties(LIST_ARTIFACTS_SPEC))

    def test_existing_properties_survive(self):
        spec = {"parameters": {"properties": {"path": {"type": "string"}}}}
        self.assertIn("path", properties(inject_depends_on_spec(spec)))

    def test_a_spec_with_no_parameters_gains_them(self):
        self.assertIn(DEPENDS_ON_PARAM, properties(inject_depends_on_spec({})))

    def test_none_is_tolerated(self):
        self.assertIn(DEPENDS_ON_PARAM, properties(inject_depends_on_spec(None)))

    def test_other_spec_fields_are_preserved(self):
        spec = {"name": "t", "description": "d", "parameters": {"properties": {}}}
        injected = inject_depends_on_spec(spec)
        self.assertEqual(injected["name"], "t")
        self.assertEqual(injected["description"], "d")

    def test_a_non_dict_parameters_value_is_replaced_rather_than_crashing(self):
        injected = inject_depends_on_spec({"parameters": "not a dict"})
        self.assertIn(DEPENDS_ON_PARAM, properties(injected))


class OnlyTheChatLoopInjectsTest(unittest.TestCase):
    def test_the_core_catalog_producer_does_not_inject(self):
        import ast
        import pathlib

        from open_webui.utils import tools

        source = pathlib.Path(tools.__file__).read_text()
        names = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom):
                names.update(alias.name for alias in node.names)
        self.assertNotIn("inject_depends_on_spec", names)


if __name__ == "__main__":
    unittest.main()
