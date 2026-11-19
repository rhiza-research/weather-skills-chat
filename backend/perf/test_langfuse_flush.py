"""Langfuse tracing (#59): a long agent turn with tracing on, as in prod.

Each model call ended with client.flush(), a synchronous HTTP export to
Langfuse Cloud, and the turn's end waited up to 5 s for the trace input
thread, all on the event loop.
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from perf_harness import LoopProbe, check_budget, record

ROUNDS = 38  # model rounds in the turn before prod's 16:39 UTC restart
MESSAGES = [{"role": "user", "content": "Plot weekly rainfall " * 100}] * 20

# client.flush() blocks until the HTTP export finishes (checked against a slow
# local OTLP sink: +100 ms there, +100 ms per flush). From the staging pod to
# us.cloud.langfuse.com an export takes 55 ms when small and 357 ms for 900 KB.
SMALL_EXPORT_S = 0.055
# Prod model requests were 439 KB at the median (882 calls, 2026-10-21).
MEDIAN_GENERATION_EXPORT_S = 0.2

# How a connection's model calls are traced (model_call_tracing):
# - "app": the app records each call as a generation and flushed after every
#   call, exporting that call's input.
# - "openrouter": OpenRouter Broadcast records the calls; the app only flushed
#   at the end of the turn, exporting the root span (input capped at 32k chars).
MODES = [
    pytest.param("app", MEDIAN_GENERATION_EXPORT_S, "flush per model call, median input", id="app-median"),
    pytest.param("app", SMALL_EXPORT_S, "flush per model call, small input", id="app-small"),
    pytest.param("openrouter", SMALL_EXPORT_S, "flush at end of turn", id="openrouter"),
]


@pytest.mark.parametrize("style,flush_s,label", MODES)
def test_traced_tool_loop(tmp_path, style, flush_s, label):
    from open_webui.utils import langfuse_tracing as lf

    client = MagicMock()
    client.flush.side_effect = lambda: time.sleep(flush_s)
    client.start_observation.return_value = MagicMock(trace_id="a" * 32, id="b" * 16)
    form_data = {"model": "weather-agent", "messages": MESSAGES}

    async def model_call():
        await asyncio.sleep(0.02)
        return {
            "choices": [{"message": {"role": "assistant", "content": "calling a tool"}}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 50},
        }

    async def run():
        async with LoopProbe() as probe:
            lf.begin_chat_trace(
                user=SimpleNamespace(email="perf@example.com", id="perf-user"),
                metadata={"chat_id": "chat-perf", "message_id": "msg-perf"},
                form_data=form_data,
            )
            for _ in range(ROUNDS):
                await lf.observe_generation(form_data, model_call(), style=style)
                await asyncio.sleep(0.01)  # the tool
            lf.end_chat_trace(output={"content": "done"})
        return probe.stats

    with patch.object(lf, "tracing_enabled", return_value=True), patch.object(
        lf, "get_client", return_value=client
    ), patch("langfuse.propagate_attributes", create=True):
        stats = asyncio.run(run())

    record(f"langfuse ({style}): {ROUNDS}-round turn, {label}, {int(flush_s * 1000)} ms export", stats)
    # One 55 ms end-of-turn export is the old cost in openrouter mode, so its
    # budget sits below that.
    check_budget(stats, max_lag_ms=40 if style == "openrouter" else 100, blocked_pct=5)
