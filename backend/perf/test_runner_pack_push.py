"""Runner start (#60): pushing the chat's skill packs to a fresh runner.

Each pack was read from JuiceFS, tarred, gzipped and base64-encoded, and the
upload body JSON-encoded, on the event loop, one pack after another. Prod
logs: 249 pushes in 24 h, 0.5 s median each, ~9 packs per start.
"""

import asyncio
import os
import time
from unittest.mock import patch

from perf_harness import DB_STATEMENT_S, LoopProbe, check_budget, fs_delay, record
from perf_harness.data import build_skill_packs

PACKS = 9


def test_runner_start_pushes_packs(tmp_path):
    from open_webui.utils import skill_k8s_sandbox as sk

    juicefs = tmp_path / "juicefs"
    skills = juicefs / "skills"
    packs = build_skill_packs(skills, packs=PACKS)

    def packs_for_chat(chat_id):
        # Stands in for the chat, user, tool catalog and skill-record reads.
        for _ in range(6):
            time.sleep(DB_STATEMENT_S)
        return packs

    async def listed_packs(info):
        await asyncio.sleep(0.02)  # GET /packs on the runner
        return set()

    async def runner_base(*args, **kwargs):
        return "http://runner"

    async def upload(method, url, **kwargs):
        await asyncio.sleep(0.3)  # POST /unpack and the runner unpacking
        return {"ok": True}

    async def run():
        async with LoopProbe() as probe:
            await sk._ensure_packs_on_runner(
                {"pod_ip": "10.0.0.1", "pod_name": "runner-1"}, "chat-perf"
            )
        return probe.stats

    with patch.dict(os.environ, {"SKILLS_DIR": str(skills)}), patch.object(
        sk, "_packs_for_chat", packs_for_chat
    ), patch.object(sk, "_listed_packs", listed_packs), patch.object(
        sk, "_runner_base", runner_base
    ), patch.object(sk, "_http_json", upload), fs_delay([juicefs]):
        stats = asyncio.run(run())

    record(f"runner start: push {PACKS} skill packs", stats)
    # Packing runs in threads now, but nine packs compressing and encoding at
    # once still compete with the loop for the GIL; that share varies by run.
    check_budget(stats, max_lag_ms=100, blocked_pct=30)
