"""The request the endpoint builds for catalog calls names the organization the call runs in."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.mcp.auth import MCP_PATH
from open_webui.mcp.request import ORGANIZATION_HEADER, core_request
from open_webui.utils.tools import get_tools

APP = SimpleNamespace(state=SimpleNamespace(TOOLS={}))
USER = SimpleNamespace(id="account-1", role="user", settings=None)


class CoreRequestTest(unittest.TestCase):
    def test_the_request_carries_the_app_and_the_endpoint_path(self):
        request = core_request(APP, "org-1")
        self.assertIs(request.scope["app"], APP)
        self.assertEqual(request.url.path, MCP_PATH)

    def test_the_organization_is_the_only_header(self):
        request = core_request(APP, "org-1")
        self.assertEqual(dict(request.headers), {ORGANIZATION_HEADER.lower(): "org-1"})

    def test_get_tools_reads_the_organization_from_it(self):
        with patch(
            "open_webui.utils.tools.accessible_skill_records", return_value=[]
        ) as records:
            get_tools(core_request(APP, "org-1"), [], USER, {}, catalog=[])
        self.assertEqual(records.call_args.kwargs["organization_id"], "org-1")


if __name__ == "__main__":
    unittest.main()
