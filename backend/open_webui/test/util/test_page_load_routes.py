"""Page-load routes keep their database reads off the event loop."""

import asyncio
import inspect
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

# Fetched by the browser on every page load. Their handlers only make
# synchronous calls, so they are plain functions FastAPI runs in its threadpool.
PLAIN_ROUTES = [
    "/api/models",
    "/api/app_config",
    "/api/v1/user_config",
    "/api/v1/auths/",
    "/api/v1/automations/",
    "/api/v1/chats/",
    "/api/v1/chats/pinned",
    "/api/v1/chats/all/tags",
    "/api/v1/chats/recent",
    "/api/v1/configs/banners",
    "/api/v1/folders/",
    "/api/v1/models/",
    "/api/v1/organizations/",
    "/api/v1/secrets/",
    "/api/v1/skills/",
    "/api/v1/usage/me",
    "/api/v1/users/user/settings",
]


class PageLoadRoutesTest(unittest.TestCase):
    def test_page_load_handlers_are_plain_functions(self):
        from fastapi.routing import APIRoute

        import main

        handlers = {
            route.path: route.endpoint
            for route in main.app.routes
            if isinstance(route, APIRoute) and "GET" in route.methods
        }
        for path in PLAIN_ROUTES:
            self.assertIn(path, handlers)
            self.assertFalse(
                inspect.iscoroutinefunction(handlers[path]),
                f"{path} runs on the event loop",
            )


class VisibleToolsTest(unittest.TestCase):
    def test_tool_catalog_is_read_on_a_worker_thread(self):
        from open_webui.routers import tools as tools_router

        threads = {}

        def get_tools():
            threads["read"] = threading.current_thread()
            return []

        state = SimpleNamespace(TOOL_SERVERS=[], config=SimpleNamespace(TOOL_SERVER_CONNECTIONS=[]))
        request = SimpleNamespace(app=SimpleNamespace(state=state))

        async def run():
            threads["loop"] = threading.current_thread()
            return await tools_router._visible_tools(request, SimpleNamespace(id="u1"), "u1")

        with patch.object(tools_router, "get_tool_servers_data", AsyncMock(return_value=[])), patch.object(
            tools_router.Tools, "get_tools", get_tools
        ), patch.object(tools_router, "accessible_skill_records", return_value=[]):
            self.assertEqual(asyncio.run(run()), [])
        self.assertIsNot(threads["read"], threads["loop"])
