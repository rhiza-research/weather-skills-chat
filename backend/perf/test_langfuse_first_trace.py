"""Langfuse tracing: the first chat turn after the app starts.

The Langfuse client is built on first use. Importing the SDK and building the
client ran inside the first turn's begin_chat_trace, on the event loop.
"""

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from perf_harness import LoopProbe, check_budget, record

# The first traced turn on staging after a restart spent 555 ms in
# begin_chat_trace; later turns spent 2-3 ms (chat-timing langfuse_start,
# 2026-10-22). In a fresh process on the staging pod, importing langfuse took
# 955 ms and building the client 154 ms; the app had already loaded part of
# the import.
FIRST_CLIENT_S = 0.555

MESSAGES = [{"role": "user", "content": "Plot weekly rainfall " * 100}] * 20


def test_first_traced_turn_after_startup():
    import main
    from open_webui.utils import langfuse_tracing as lf

    client = MagicMock()
    client.start_observation.return_value = MagicMock(trace_id="a" * 32, id="b" * 16)

    def build_client(**kwargs):
        time.sleep(FIRST_CLIENT_S)
        return client

    async def no_cleanup():
        return None

    async def run():
        # Startup as in production, minus the scheduler, model loads and
        # skill resync, which have their own threads or tests.
        async with main.lifespan(main.app):
            async with LoopProbe() as probe:
                lf.begin_chat_trace(
                    user=SimpleNamespace(email="perf@example.com", id="perf-user"),
                    metadata={"chat_id": "chat-perf", "message_id": "msg-perf"},
                    form_data={"model": "weather-agent", "messages": MESSAGES},
                )
                await asyncio.sleep(0.02)
                lf.end_chat_trace(output={"content": "done"})
        return probe.stats

    with patch.object(lf, "tracing_enabled", return_value=True), patch.object(
        lf, "_client", None
    ), patch.object(lf, "_client_failed", False), patch(
        "langfuse.Langfuse", side_effect=build_client
    ), patch("langfuse.propagate_attributes", create=True), patch.object(
        main, "start_logger"
    ), patch.object(main, "periodic_usage_pool_cleanup", no_cleanup), patch.object(
        main, "ensure_retrieval_models"
    ), patch.object(main, "_resync_skill_packs"), patch(
        "open_webui.utils.bootstrap.bootstrap_admin_user"
    ), patch("open_webui.utils.automation_scheduler.start_scheduler"), patch(
        "open_webui.utils.automation_scheduler.shutdown_scheduler"
    ):
        stats = asyncio.run(run())

    record(f"langfuse: first traced turn after startup, {int(FIRST_CLIENT_S * 1000)} ms client build", stats)
    check_budget(stats, max_lag_ms=25, pending="Langfuse client built in the first chat turn")
