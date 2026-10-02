"""The endpoint's run context, checked against the keys the skill runner reads.

The runner reads the session from metadata["chat_id"]. Without it, the runner writes to a directory
shared across accounts and skips confinement. It resolves stored secrets in the organization named by
metadata["organization_id"]. The key names are checked against the runner's source.
"""

import ast
import pathlib
import unittest
from types import SimpleNamespace

from fastmcp.exceptions import ToolError

from open_webui.mcp.run import (
    HEADLESS_METADATA_KEY,
    NO_SESSION_SENTINEL,
    ORGANIZATION_METADATA_KEY,
    SESSION_METADATA_KEY,
    run_context,
)
from open_webui.utils import skill_runtime

ACCOUNT = SimpleNamespace(
    id="account-1", email="priya@example.com", name="Priya", role="user"
)
SESSION = "b2c3d4e5-0000-4000-8000-000000000000"
ORG = "org-1"


class KeyNameMatchesTheRunnerTest(unittest.TestCase):
    def test_the_runner_reads_the_key_this_module_writes(self):
        source = pathlib.Path(skill_runtime.__file__).read_text()
        read_keys = set()
        for node in ast.walk(ast.parse(source)):
            # metadata.get("chat_id")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and ast.unparse(node.func.value) == "metadata"
            ):
                read_keys.add(node.args[0].value)
        self.assertIn(
            SESSION_METADATA_KEY,
            read_keys,
            f"the runner reads {sorted(read_keys)}, not {SESSION_METADATA_KEY!r}",
        )

    def test_the_sentinel_matches_the_runner(self):
        source = pathlib.Path(skill_runtime.__file__).read_text()
        self.assertIn(f'!= "{NO_SESSION_SENTINEL}"', source)


class RunContextTest(unittest.TestCase):
    def setUp(self):
        self.context = run_context(ACCOUNT, SESSION, ORG)

    def test_the_session_travels_under_the_key_the_runner_reads(self):
        self.assertEqual(
            self.context["__metadata__"][SESSION_METADATA_KEY], SESSION
        )

    def test_the_organization_travels_under_the_key_the_runner_reads(self):
        self.assertEqual(
            self.context["__metadata__"][ORGANIZATION_METADATA_KEY], ORG
        )

    def test_the_caller_travels_so_a_skill_can_receive_its_secret(self):
        self.assertEqual(self.context["__user__"]["id"], ACCOUNT.id)
        self.assertEqual(self.context["__user__"]["role"], ACCOUNT.role)

    def test_no_secret_value_is_in_the_context(self):
        # The runner looks up stored secrets from the caller's id.
        self.assertEqual(
            sorted(self.context["__user__"]), ["email", "id", "name", "role"]
        )

    def test_the_headless_convention_is_used_rather_than_a_new_stub(self):
        self.assertTrue(self.context["__metadata__"][HEADLESS_METADATA_KEY])

    def test_no_model_is_named(self):
        self.assertNotIn("__model__", self.context)

    def test_no_question_channel_is_offered(self):
        # The MCP revision the endpoint implements has no server-to-client requests. Tools that ask
        # the caller a question are not published to the endpoint.
        self.assertNotIn("__event_call__", self.context)

    def test_no_request_is_carried(self):
        self.assertNotIn("__request__", self.context)


class SecretsComeFromTheCallerTest(unittest.TestCase):
    """The runner resolves stored secrets from __user__ in the organization in __metadata__, for
    endpoint and interface runs alike."""

    def resolve_calls(self):
        source = pathlib.Path(skill_runtime.__file__).read_text()
        return [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "resolve_env_secrets_for_user"
        ]

    def test_the_runner_resolves_secrets_from_the_caller(self):
        resolved_from = set()
        for node in self.resolve_calls():
            resolved_from.update(ast.unparse(a) for a in node.args)
        self.assertIn("__user__", resolved_from, sorted(resolved_from))

    def test_the_runner_resolves_secrets_in_the_organization_this_module_writes(self):
        organization_arguments = [
            ast.unparse(keyword.value)
            for node in self.resolve_calls()
            for keyword in node.keywords
            if keyword.arg == "organization_id"
        ]
        self.assertTrue(organization_arguments)
        for argument in organization_arguments:
            self.assertIn(repr(ORGANIZATION_METADATA_KEY), argument)

    def test_the_context_names_no_secret(self):
        rendered = repr(run_context(ACCOUNT, SESSION, ORG))
        for word in ("secret", "token", "password", "api_key"):
            self.assertNotIn(word, rendered.lower())


class RefusesWithoutASessionTest(unittest.TestCase):
    def test_an_empty_session_is_refused(self):
        with self.assertRaises(ToolError):
            run_context(ACCOUNT, "", ORG)

    def test_the_runner_sentinel_is_refused(self):
        # The runner treats this value the same as a missing session.
        with self.assertRaises(ToolError):
            run_context(ACCOUNT, NO_SESSION_SENTINEL, ORG)

    def test_none_is_refused(self):
        with self.assertRaises(ToolError):
            run_context(ACCOUNT, None, ORG)


if __name__ == "__main__":
    unittest.main()
