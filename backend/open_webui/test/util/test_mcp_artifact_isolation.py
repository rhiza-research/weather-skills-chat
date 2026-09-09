"""A caller cannot choose which session's artifacts a tool reads.

The session id a tool receives comes from the resolved account, never from the call's arguments.
The listing tool's own access check also admits organization members and admins to a chat shared
with the organization, so these tests check that no caller-supplied session id reaches it.
"""

import ast
import inspect
import pathlib
import unittest

from open_webui.mcp import catalog, run, session, tools, transcript
from open_webui.mcp.run import SESSION_METADATA_KEY, run_context
from open_webui.utils.builtin_tools import list_artifacts

ENDPOINT_MODULES = (catalog, run, session, tools, transcript)


def module_source(module):
    return pathlib.Path(module.__file__).read_text()


class TheSessionIsNeverCallerSuppliedTest(unittest.TestCase):
    def test_no_endpoint_module_reads_a_session_out_of_call_arguments(self):
        # context.message.arguments is caller-controlled.
        for module in ENDPOINT_MODULES:
            for node in ast.walk(ast.parse(module_source(module))):
                if isinstance(node, ast.Subscript):
                    target = ast.unparse(node)
                    if "arguments" in target:
                        self.assertNotIn(
                            SESSION_METADATA_KEY,
                            target,
                            f"{module.__name__} indexes a session out of caller arguments",
                        )

    def test_the_run_context_is_the_only_place_the_session_key_is_written(self):
        writers = [
            module.__name__
            for module in ENDPOINT_MODULES
            if f'"{SESSION_METADATA_KEY}"' in module_source(module)
        ]
        self.assertEqual(writers, ["open_webui.mcp.run"])

    def test_the_session_in_a_run_context_is_the_argument_it_was_given(self):
        context = run_context(
            _account(), "b2c3d4e5-0000-4000-8000-000000000000", "org-1"
        )
        self.assertEqual(
            context["__metadata__"][SESSION_METADATA_KEY],
            "b2c3d4e5-0000-4000-8000-000000000000",
        )


class TheListingToolTakesNoSessionFromTheCallerTest(unittest.TestCase):
    def test_its_only_caller_facing_argument_is_a_path(self):
        # A chat id argument would let an agent name another account's session.
        parameters = inspect.signature(list_artifacts).parameters
        caller_facing = [
            name for name in parameters if not name.startswith("__")
        ]
        self.assertEqual(caller_facing, ["path"])

    def test_it_reads_the_session_from_the_context_rather_than_an_argument(self):
        source = inspect.getsource(list_artifacts)
        self.assertIn(f'metadata.get("{SESSION_METADATA_KEY}")', source)


def _account():
    from types import SimpleNamespace

    return SimpleNamespace(
        id="account-1", email="priya@example.com", name="Priya", role="user"
    )


if __name__ == "__main__":
    unittest.main()
