import sys
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from open_webui.routers import tool_runner as tool_runner_router


def _fake_realtime():
    mod = MagicMock()
    mod.schedule_runner_metrics = MagicMock()
    mod.emit_chat_runner = AsyncMock()
    return mod


class ToolRunnerRoutesTest(IsolatedAsyncioTestCase):
    async def test_get_does_not_start_and_reports_paused(self):
        user = MagicMock()
        realtime = _fake_realtime()
        with (
            patch.dict(sys.modules, {"open_webui.utils.chat_realtime": realtime}),
            patch(
                "open_webui.routers.tool_runner.tool_runner_enabled", return_value=True
            ),
            patch("open_webui.routers.tool_runner.require_chat_read"),
            patch(
                "open_webui.utils.skill_k8s_sandbox.runner_status",
                new_callable=AsyncMock,
                return_value={"state": "absent"},
            ),
            patch("open_webui.utils.skill_k8s_sandbox.start_runner") as start,
        ):
            body = await tool_runner_router.get_tool_runner("chat-1", user=user)
        start.assert_not_called()
        realtime.schedule_runner_metrics.assert_called_once_with("chat-1")
        self.assertEqual(body["state"], "paused")
        self.assertTrue(body["enabled"])

    async def test_get_reports_ready_when_a_runner_is_up(self):
        user = MagicMock()
        realtime = _fake_realtime()
        with (
            patch.dict(sys.modules, {"open_webui.utils.chat_realtime": realtime}),
            patch(
                "open_webui.routers.tool_runner.tool_runner_enabled", return_value=True
            ),
            patch("open_webui.routers.tool_runner.require_chat_read"),
            patch(
                "open_webui.utils.skill_k8s_sandbox.runner_status",
                new_callable=AsyncMock,
                return_value={"state": "ready", "claim": "runner-chat-1"},
            ),
            patch("open_webui.utils.skill_k8s_sandbox.start_runner") as start,
        ):
            body = await tool_runner_router.get_tool_runner("chat-1", user=user)
        start.assert_not_called()
        self.assertEqual(body["state"], "ready")

    async def test_post_starts_and_emits_starting(self):
        user = MagicMock()
        realtime = _fake_realtime()
        with (
            patch.dict(sys.modules, {"open_webui.utils.chat_realtime": realtime}),
            patch(
                "open_webui.routers.tool_runner.tool_runner_enabled", return_value=True
            ),
            patch("open_webui.routers.tool_runner.require_chat_read"),
            patch(
                "open_webui.utils.skill_k8s_sandbox.runner_status",
                new_callable=AsyncMock,
                return_value={"state": "absent"},
            ),
            patch("open_webui.utils.skill_k8s_sandbox.start_runner") as start,
        ):
            body = await tool_runner_router.start_tool_runner("chat-1", user=user)
        start.assert_called_once_with("chat-1")
        self.assertEqual(body["state"], "starting")
        realtime.emit_chat_runner.assert_awaited()
        self.assertEqual(
            realtime.emit_chat_runner.await_args.args[1]["state"], "starting"
        )
