"""The system message names the chat's tools in sorted order, so the same tools
sent in a different order keep the provider's prompt cache."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui.utils import middleware

HINT = "Tools/skills enabled for this chat: "


def _tools(names):
    """A tools_dict with one tool per name, inserted in the given order."""
    return {
        name: {"spec": {"name": name, "parameters": {"type": "object", "properties": {}}}}
        for name in names
    }


class ToolNameHintTest(unittest.IsolatedAsyncioTestCase):
    async def _messages(self, tools):
        """The messages a native-function-calling request sends with these tools."""

        def load(request, user, metadata, tool_extra, model_id, clock):
            return middleware.PayloadContext(
                tools=tools, tool_ids=None, secret_hint="", model_params=None, preferences=None
            )

        config = SimpleNamespace(TASK_MODEL="", TASK_MODEL_EXTERNAL="", RENDERING_PROMPT="")
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(config=config, MODELS={"m": {"id": "m"}})),
            state=SimpleNamespace(),
        )
        user = SimpleNamespace(id="u1", email="u1@example.com", name="U", role="user")
        form = {"model": "m", "messages": [{"role": "user", "content": "Rain?"}]}
        metadata = {
            "chat_id": "chat-1",
            "organization_id": "org-1",
            "function_calling": "native",
        }
        with patch.object(
            middleware, "start_chat_payload", side_effect=lambda f, m: (f, [])
        ), patch.object(
            middleware, "load_payload_context", side_effect=load
        ), patch.object(
            middleware, "process_pipeline_inlet_filter", AsyncMock(side_effect=lambda r, f, u, m: f)
        ), patch.object(
            middleware,
            "chat_completion_files_handler",
            AsyncMock(side_effect=lambda r, f, u: (f, {})),
        ), patch(
            "open_webui.env.tool_runner_enabled", return_value=False
        ):
            form_data, _, _ = await middleware.process_chat_payload(
                request, form, user, metadata, {"id": "m"}
            )
        return form_data["messages"]

    async def _system(self, tools):
        system = [m for m in await self._messages(tools) if m.get("role") == "system"]
        self.assertEqual(len(system), 1)
        return system[0]["content"]

    async def test_same_tools_in_another_order_give_the_same_system_message(self):
        first = await self._system(_tools(["plot", "imerg_fetch", "clip_region"]))
        second = await self._system(_tools(["clip_region", "plot", "imerg_fetch"]))

        self.assertEqual(first, second)
        self.assertIn(HINT + "`clip_region`, `imerg_fetch`, `plot`.", first)

    async def test_another_tool_set_changes_the_line(self):
        before = await self._system(_tools(["plot", "imerg_fetch"]))
        after = await self._system(_tools(["plot", "imerg_fetch", "clip_region"]))

        self.assertNotEqual(before, after)
        self.assertIn(HINT + "`imerg_fetch`, `plot`.", before)
        self.assertIn(HINT + "`clip_region`, `imerg_fetch`, `plot`.", after)

    async def test_no_line_when_no_tool_has_a_name(self):
        messages = await self._messages({"nameless": {"spec": {}}})

        self.assertNotIn(HINT, str(messages))


if __name__ == "__main__":
    unittest.main()
