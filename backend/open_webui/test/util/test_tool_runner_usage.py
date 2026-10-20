"""Tool runner usage reaches the tool's Langfuse observation, never the model."""

import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.responses import StreamingResponse

import open_webui.utils.middleware as mw
from open_webui.utils.skill_k8s_sandbox import TOOL_RUNNER_USAGE_KEY

USAGE = {"cpu_seconds": 1.5, "peak_memory_bytes": 2048, "run_seconds": 2.25}
SPAN = object()


async def run_x():
    return {
        "ok": True,
        "stdout": "skill finished",
        "tool_runner": True,
        TOOL_RUNNER_USAGE_KEY: dict(USAGE),
    }


TOOLS = {
    "run_x": {
        "spec": {
            "name": "run_x",
            "parameters": {"type": "object", "properties": {}},
        },
        "callable": run_x,
    }
}
USER = SimpleNamespace(id="user-1", email="user@example.com", name="User", role="user")


def _sse(*events):
    async def body():
        for event in events:
            yield f"data: {json.dumps(event)}\n"
        yield "data: [DONE]\n"

    return StreamingResponse(body(), media_type="text/event-stream")


async def _filters(request, filter_functions, filter_type, form_data, extra_params):
    return form_data, {}


def _call_params(call: dict) -> dict:
    if "function" in call:
        return json.loads(call["function"].get("arguments") or "{}")
    return dict(call.get("parameters") or {})


def _patch_common(stack: ExitStack) -> MagicMock:
    stack.enter_context(
        patch(
            "open_webui.utils.secrets.scrub_tool_call_in_place",
            side_effect=_call_params,
        )
    )
    stack.enter_context(
        patch("open_webui.utils.secrets.sensitive_values_from_params", return_value={})
    )
    stack.enter_context(
        patch(
            "open_webui.utils.secrets.apply_secrets_for_tool",
            side_effect=lambda params, user, **kwargs: (params, {}),
        )
    )
    stack.enter_context(
        patch(
            "open_webui.utils.secrets.redact_secrets",
            side_effect=lambda value, secrets: value,
        )
    )
    stack.enter_context(
        patch.object(mw, "start_tool_observation", return_value=SPAN)
    )
    return stack.enter_context(patch.object(mw, "end_tool_observation"))


class NativeToolLoopTest(unittest.IsolatedAsyncioTestCase):
    async def test_usage_goes_to_the_span_and_not_the_model(self):
        followups = []

        async def followup(request, form_data, user):
            followups.append(form_data)
            return _sse({"choices": [{"delta": {"content": "All done."}}]})

        first = _sse(
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {"name": "run_x", "arguments": "{}"},
                                }
                            ]
                        }
                    }
                ]
            }
        )
        metadata = {
            "chat_id": "chat-1",
            "message_id": "msg-1",
            "session_id": "sess-1",
            "tools": TOOLS,
        }
        form_data = {
            "model": "m",
            "messages": [{"role": "user", "content": "run it"}],
            "tools": [{"type": "function", "function": TOOLS["run_x"]["spec"]}],
        }

        with ExitStack() as stack:
            end_obs = _patch_common(stack)
            stack.enter_context(
                patch.object(mw, "get_event_emitter", return_value=AsyncMock())
            )
            stack.enter_context(
                patch.object(mw, "get_event_call", return_value=AsyncMock())
            )
            stack.enter_context(patch.object(mw, "get_sorted_filter_ids", return_value=[]))
            stack.enter_context(
                patch.object(mw, "process_filter_functions", side_effect=_filters)
            )
            stack.enter_context(
                patch.object(mw, "generate_chat_completion", side_effect=followup)
            )
            stack.enter_context(patch.object(mw, "end_chat_trace"))
            stack.enter_context(
                patch.object(mw, "get_active_status_by_user_id", return_value="active")
            )
            stack.enter_context(
                patch.object(mw.Chats, "upsert_message_to_chat_by_id_and_message_id")
            )
            stack.enter_context(
                patch.object(mw.Chats, "get_message_by_id_and_message_id", return_value=None)
            )
            stack.enter_context(
                patch.object(mw.Chats, "get_chat_title_by_id", return_value="Chat")
            )
            stack.enter_context(
                patch.object(mw.Chats, "get_messages_by_chat_id", return_value={})
            )
            stack.enter_context(patch.object(mw.Chats, "get_chat_revision", return_value=1))
            stack.enter_context(
                patch(
                    "open_webui.utils.chat_realtime.save_final_reply",
                    new_callable=AsyncMock,
                    return_value=True,
                )
            )
            stack.enter_context(
                patch("open_webui.utils.chat.chat_completed", new_callable=AsyncMock)
            )
            stack.enter_context(
                patch("open_webui.utils.skill_k8s_sandbox.runner_ready", return_value=True)
            )
            await mw.process_chat_response(
                MagicMock(),
                first,
                form_data,
                USER,
                metadata,
                {"id": "m"},
                [],
                None,
                detach=False,
            )

        self.assertEqual(len(followups), 1)
        tool_messages = [
            m for m in followups[0]["messages"] if m.get("role") == "tool"
        ]
        self.assertEqual(len(tool_messages), 1)
        content = json.dumps(tool_messages[0]["content"])
        self.assertIn("skill finished", content)
        self.assertNotIn(TOOL_RUNNER_USAGE_KEY, content)
        self.assertNotIn("cpu_seconds", content)

        end_obs.assert_called_once()
        self.assertIs(end_obs.call_args.args[0], SPAN)
        self.assertEqual(end_obs.call_args.kwargs["metadata"], USAGE)
        self.assertNotIn(TOOL_RUNNER_USAGE_KEY, end_obs.call_args.kwargs["output"])


class NonNativeToolHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_usage_goes_to_the_span_and_not_the_model(self):
        request = MagicMock()
        request.app.state.config.TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE = ""
        body = {"model": "m", "messages": [{"role": "user", "content": "run it"}]}
        reply = {
            "choices": [
                {"message": {"content": json.dumps({"name": "run_x", "parameters": {}})}}
            ]
        }

        with ExitStack() as stack:
            end_obs = _patch_common(stack)
            stack.enter_context(patch.object(mw, "get_task_model_id", return_value="m"))
            stack.enter_context(
                patch.object(
                    mw, "generate_chat_completion", new_callable=AsyncMock, return_value=reply
                )
            )
            body, _ = await mw.chat_completion_tools_handler(
                request,
                body,
                {"__event_call__": AsyncMock(), "__metadata__": {}},
                USER,
                {},
                TOOLS,
            )

        sent = json.dumps(body["messages"])
        self.assertIn("skill finished", sent)
        self.assertNotIn(TOOL_RUNNER_USAGE_KEY, sent)
        self.assertNotIn("cpu_seconds", sent)

        end_obs.assert_called_once()
        self.assertIs(end_obs.call_args.args[0], SPAN)
        self.assertEqual(end_obs.call_args.kwargs["metadata"], USAGE)


if __name__ == "__main__":
    unittest.main()
