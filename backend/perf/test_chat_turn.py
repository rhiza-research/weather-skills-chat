"""One chat turn end to end (#4, #6): POST /api/chat/completions on the full app.

Before the model is called, the request is checked and prepared: chat
ownership, the model and its access, usage caps, the tool catalog, skill
records, secrets and filters, each a database read. Every model round repeats
the model, access and usage checks, and the end of the turn reloads the whole
chat several times. These reads ran on the event loop.

The provider is a fake at the aiohttp level, so the app's own request
building, checks and streaming all run. It answers with a built-in tool call
for ROUNDS rounds, then streams the reply.
"""

import asyncio
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, patch

import httpx

from perf_harness import LoopProbe, check_budget, db_delay, record
from perf_harness.app_data import ensure_user, insert_chat
from perf_harness.data import big_chat

ROUNDS = 6
REPLY_DELTAS = 120
FIRST_BYTE_S = 0.05  # provider time to first byte; the loop is free meanwhile
# Prod (2026-10-21 chat-timing logs): a 164-tool catalog, 65 tools enabled on a
# chat with their modules already loaded, and 8 saved secrets.
CATALOG_TOOLS = 164
CHAT_TOOLS = 65
SECRETS = 8

TOOL_SOURCE = """
class Tools:
    def run_{i}(self, region: str = "") -> str:
        \"\"\"Run step {i} for a region.\"\"\"
        return region
"""


class _Content:
    def __init__(self, lines):
        self._lines = lines

    def __aiter__(self):
        return self._iter()

    async def _iter(self):
        for line in self._lines:
            yield line


class _Response:
    status = 200
    headers = {"Content-Type": "text/event-stream"}

    def __init__(self, lines):
        self.content = _Content(lines)

    def raise_for_status(self):
        return None

    def release(self):
        return None

    def close(self):
        return None

    async def json(self):
        return {}

    async def text(self):
        return ""


def _sse(chunks):
    lines = [f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks]
    return lines + [b"data: [DONE]\n\n"]


class FakeProvider:
    """Stands in for aiohttp.ClientSession in the OpenAI router."""

    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    async def request(self, method, url, data=None, headers=None, **kwargs):
        FakeProvider.calls += 1
        await asyncio.sleep(FIRST_BYTE_S)
        body = json.loads(data)
        tool_results = sum(1 for m in body.get("messages", []) if m.get("role") == "tool")
        if tool_results < ROUNDS:
            call = {
                "index": 0,
                "id": f"call_{tool_results}",
                "type": "function",
                "function": {"name": "list_preferences", "arguments": "{}"},
            }
            return _Response(_sse([{"choices": [{"delta": {"tool_calls": [call]}}]}]))
        words = [{"choices": [{"delta": {"content": f"word{i} "}}]} for i in range(REPLY_DELTAS)]
        words.append({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 9000, "completion_tokens": REPLY_DELTAS}})
        return _Response(_sse(words))

    async def close(self):
        return None

    # Other aiohttp users on the path (the pipelines inlet filter) open a
    # session as a context manager even with no pipelines configured.
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _tools_and_secrets(app, user) -> list[str]:
    """The catalog, the chat's enabled tools with warm modules, and saved secrets."""
    from open_webui.models.secrets import SecretForm, Secrets
    from open_webui.models.tools import ToolForm, ToolMeta, Tools
    from open_webui.utils.plugin import load_tool_module_by_id

    tool_ids = []
    for i in range(CATALOG_TOOLS):
        tool_id = f"perf_tool_{i}"
        if Tools.get_tool_by_id(tool_id) is None:
            spec = {
                "name": f"run_{i}",
                "description": f"Run step {i} for a region.",
                "parameters": {"type": "object", "properties": {"region": {"type": "string"}}},
            }
            Tools.insert_new_tool(
                "perf-admin",
                ToolForm(id=tool_id, name=f"Step {i}", content=TOOL_SOURCE.format(i=i), meta=ToolMeta()),
                [spec],
            )
        if i < CHAT_TOOLS:
            tool_ids.append(tool_id)
            app.state.TOOLS[tool_id], _ = load_tool_module_by_id(tool_id)
    if len(Secrets.list_for_org(user.id, user.id)) < SECRETS:
        for i in range(SECRETS):
            Secrets.insert(user.id, SecretForm(name=f"PERF_KEY_{i}", value="v" * 32))
    return tool_ids


def _optional(stack, target, attribute, value):
    """Patch an attribute when this checkout of the app has it."""
    if hasattr(target, attribute):
        stack.enter_context(patch.object(target, attribute, value))


def test_one_chat_turn_with_tool_rounds(tmp_path):
    import main
    from open_webui.models.models import ModelForm, Models
    from open_webui.routers import openai as openai_router
    from open_webui.utils import middleware
    from open_webui.utils.auth import get_verified_user

    user = ensure_user()
    chat_id = insert_chat(user.id, big_chat(1_500_000))
    if Models.get_model_by_id("weather-agent") is None:
        Models.insert_new_model(
            ModelForm(
                id="weather-agent",
                base_model_id="openai/gpt-4o",
                name="Weather Agent",
                meta={},
                params={"function_calling": "native"},
                organization_id=user.id,
                visibility="private",
            ),
            user.id,
        )
    app = main.app
    tool_ids = _tools_and_secrets(app, user)
    config = app.state.config
    config.OPENAI_API_BASE_URLS = ["https://provider.test/v1"]
    config.OPENAI_API_KEYS = ["perf-key"]
    config.OPENAI_API_CONFIGS = {"0": {"enable": True}}
    app.dependency_overrides[get_verified_user] = lambda: user

    done = asyncio.Event
    events = []
    state = {}

    async def emit(event):
        events.append(event)
        data = event.get("data") if isinstance(event, dict) else None
        if event.get("type") == "chat:completion" and isinstance(data, dict) and data.get("done"):
            state["done"].set()

    form = {
        "model": "weather-agent",
        "messages": [{"role": "user", "content": "What preferences do I have saved?"}],
        "stream": True,
        "chat_id": chat_id,
        "id": "msg-perf",
        "session_id": "sess-perf",
        "background_tasks": {},
        "params": {"function_calling": "native"},
        "features": {},
        "tool_ids": tool_ids,
    }

    async def run():
        state["done"] = done()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://perf", timeout=60) as client:
            async with LoopProbe() as probe:
                response = await client.post("/api/chat/completions", json=form)
                assert response.status_code == 200, response.text
                await asyncio.wait_for(state["done"].wait(), timeout=60)
        return probe.stats

    FakeProvider.calls = 0
    with ExitStack() as stack:
        stack.enter_context(patch.object(openai_router.aiohttp, "ClientSession", FakeProvider))
        for module in (main, middleware):
            _optional(stack, module, "get_event_emitter", lambda *a, **k: emit)
            _optional(stack, module, "get_event_call", lambda *a, **k: AsyncMock())
        stack.enter_context(db_delay())
        stats = asyncio.run(run())

    assert FakeProvider.calls == ROUNDS + 1, FakeProvider.calls
    record(
        f"chat turn: {ROUNDS} tool rounds + reply, 1.5 MB chat, {CHAT_TOOLS} tools, {SECRETS} secrets",
        stats,
        model_calls=FakeProvider.calls,
    )
    check_budget(stats, max_lag_ms=50, blocked_pct=5, pending="#4 per-message and per-round prep, #6 chat load logging")
