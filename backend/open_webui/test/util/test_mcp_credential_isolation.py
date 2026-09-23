"""The endpoint's modules import and read none of the interface's credential paths directly.

Checked against the module source, because the property is that these names are absent. Only
direct imports by modules in the endpoint's package are checked. The package imports the
authorization server's consent routes from open_webui.mcp_oauth, which read the interface's
session cookie; tool code does not use them.
"""

import ast
import pathlib
import unittest

from open_webui import mcp

# Names the interface uses to resolve a caller to an account: FastAPI dependency callables, the
# decoder for the interface's own token, and the trusted-header sign-in.
INTERFACE_CALLER_PATHS = (
    "get_current_user",
    "get_verified_user",
    "get_admin_user",
    "get_current_user_by_api_key",
    "bearer_security",
    "decode_token",
    "authenticate_user_by_trusted_header",
)

# Attributes the interface reads off a request to identify a caller.
INTERFACE_CREDENTIAL_NAMES = ("token", "api_key", "session")

ENDPOINT_MODULE_DIR = pathlib.Path(mcp.__file__).parent


def endpoint_modules():
    return sorted(ENDPOINT_MODULE_DIR.glob("*.py"))


def imported_names(source):
    """Every name the module binds by import, whether by module or by member."""
    names = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
            if node.module:
                names.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


class EndpointModuleImportsTest(unittest.TestCase):
    def test_there_is_something_to_check(self):
        # An empty glob would make every assertion below pass without checking anything.
        self.assertGreater(len(endpoint_modules()), 1)

    def test_no_interface_caller_path_is_imported(self):
        for path in endpoint_modules():
            names = imported_names(path.read_text())
            for forbidden in INTERFACE_CALLER_PATHS:
                self.assertNotIn(
                    forbidden,
                    names,
                    f"{path.name} imports {forbidden}, which resolves an interface credential",
                )

    def test_the_interface_auth_module_is_not_imported(self):
        for path in endpoint_modules():
            names = imported_names(path.read_text())
            self.assertNotIn("open_webui.utils.auth", names, path.name)

    def test_no_chat_loop_module_is_imported(self):
        # The chat loop is spread across these three modules.
        for path in endpoint_modules():
            names = imported_names(path.read_text())
            for forbidden in (
                "open_webui.utils.middleware",
                "open_webui.utils.chat",
                "open_webui.functions",
            ):
                self.assertNotIn(forbidden, names, path.name)


class NoTokenIsForwardedTest(unittest.TestCase):
    """The MCP specification forbids passing a received token through to another service.

    The endpoint makes no outbound requests, so these check that no module imports an HTTP client
    or reads request headers.
    """

    OUTBOUND_CLIENTS = (
        "httpx",
        "requests",
        "aiohttp",
        "urllib",
        "urllib3",
        "http.client",
    )

    def test_no_module_imports_an_outbound_http_client(self):
        for path in endpoint_modules():
            names = imported_names(path.read_text())
            for client in self.OUTBOUND_CLIENTS:
                self.assertNotIn(
                    client,
                    names,
                    f"{path.name} imports {client}, an outbound HTTP client",
                )

    def test_no_module_reads_a_header_off_anything(self):
        # Only the token verifier reads the credential.
        for path in endpoint_modules():
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Attribute):
                    self.assertNotEqual(
                        node.attr,
                        "headers",
                        f"{path.name} reads headers off {ast.unparse(node.value)}",
                    )


class AuthorizationServerOutboundTest(unittest.TestCase):
    """The authorization server's modules open no HTTP client of their own.

    Its only outbound request is the Client ID Metadata Document fetch, made by fastmcp's
    SSRF-protected fetcher.
    """

    def _modules(self):
        return sorted((ENDPOINT_MODULE_DIR.parent / "mcp_oauth").glob("*.py"))

    def test_there_is_something_to_check(self):
        self.assertGreater(len(self._modules()), 1)

    def test_no_module_imports_an_outbound_http_client(self):
        for path in self._modules():
            names = imported_names(path.read_text())
            for client in (*NoTokenIsForwardedTest.OUTBOUND_CLIENTS, "httpx2", "urllib.request"):
                self.assertNotIn(
                    client,
                    names,
                    f"{path.name} imports {client}, an outbound HTTP client",
                )


class EndpointModuleSourceTest(unittest.TestCase):
    def test_no_module_reads_a_credential_off_a_request(self):
        for path in endpoint_modules():
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                # The interface reads a caller's credential from request.cookies and
                # request.state.token.
                if isinstance(node, ast.Attribute) and node.attr in (
                    "cookies",
                    *INTERFACE_CREDENTIAL_NAMES,
                ):
                    base = ast.unparse(node.value)
                    self.assertNotIn(
                        "request",
                        base,
                        f"{path.name} reads {node.attr} off {base}",
                    )


if __name__ == "__main__":
    unittest.main()
