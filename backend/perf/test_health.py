"""Readiness check (#9): GET /health/db runs SELECT 1 on the event loop.

With a healthy database that costs a few milliseconds every 10 s. When the
database is slow, the readiness check holds the loop for as long as the query
takes, so /health, the liveness check, stalls behind it and the pod restarts
instead of only leaving the load balancer.
"""

import asyncio
import time

import pytest

from perf_harness import DB_STATEMENT_S, LoopProbe, check_budget, db_delay, record
from perf_harness.app_data import asgi_client, ensure_user, main_app

READINESS_CHECKS = 5

DATABASES = [
    pytest.param(DB_STATEMENT_S, "normal database (4 ms per statement, prod)", id="normal"),
    # Not measured: a database under load or a pool that has to wait.
    pytest.param(0.5, "slow database (500 ms per statement, what-if)", id="slow"),
]


@pytest.mark.parametrize("statement_s,label", DATABASES)
def test_readiness_check_while_liveness_is_probed(tmp_path, statement_s, label):
    user = ensure_user()
    app = main_app(user)
    liveness_ms = []

    async def run():
        async with asgi_client(app) as client:

            async def liveness():
                while True:
                    started = time.perf_counter()
                    await client.get("/health")
                    liveness_ms.append((time.perf_counter() - started) * 1000)
                    await asyncio.sleep(0.02)

            async with LoopProbe() as probe:
                prober = asyncio.create_task(liveness())
                for _ in range(READINESS_CHECKS):
                    response = await client.get("/health/db")
                    assert response.status_code == 200
                    await asyncio.sleep(0.05)
                prober.cancel()
        return probe.stats

    with db_delay(statement_s):
        stats = asyncio.run(run())
    record(f"health: {READINESS_CHECKS} readiness checks, {label}", stats, slowest_liveness_ms=round(max(liveness_ms), 1))
    # With a healthy database the check is cheap; the fix is for the slow case.
    pending = "#9 /health/db on the loop" if statement_s > DB_STATEMENT_S else None
    check_budget(stats, max_lag_ms=25, pending=pending)
