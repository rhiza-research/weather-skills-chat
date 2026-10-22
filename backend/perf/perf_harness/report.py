"""Print a scenario's numbers, save them for the comparison script, check budgets."""

from __future__ import annotations

import json
import os

from .probe import LoopStats

# Set by scripts/perf_compare.py: append each result here as one JSON line.
RESULTS_ENV = "PERF_RESULTS"
# Set by scripts/perf_compare.py for old revisions, which are expected to
# blow every budget: record the numbers, do not fail.
REPORT_ONLY_ENV = "PERF_REPORT_ONLY"


def record(scenario: str, stats: LoopStats, **extra) -> dict:
    row = {"scenario": scenario, **stats.as_dict(), **extra}
    print(
        f"\n[perf] {scenario}: max lag {row['max_lag_ms']} ms, p99 {row['p99_lag_ms']} ms, "
        f"blocked {row['blocked_pct']}% of {row['duration_s']} s"
    )
    path = os.environ.get(RESULTS_ENV)
    if path:
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    return row


def check_budget(
    stats: LoopStats,
    *,
    max_lag_ms: float,
    blocked_pct: float | None = None,
    pending: str | None = None,
):
    """Fail when the scenario held the loop longer than the budget allows.

    ``pending`` names a fix that has not landed yet. Over budget, the test is
    marked as an expected failure, so its numbers are still recorded. Within
    budget, it fails as a reminder to drop ``pending`` and enforce the budget.
    """
    if os.environ.get(REPORT_ONLY_ENV):
        return
    import pytest

    problems = []
    if stats.max_lag_ms > max_lag_ms:
        problems.append(f"event loop held for {stats.max_lag_ms:.0f} ms (budget {max_lag_ms:.0f} ms)")
    if blocked_pct is not None and stats.blocked_pct > blocked_pct:
        problems.append(f"event loop blocked {stats.blocked_pct:.1f}% of the run (budget {blocked_pct}%)")
    if pending:
        if problems:
            pytest.xfail(f"pending {pending}: " + "; ".join(problems))
        pytest.fail(f"within budget now; if {pending} is fixed, remove pending= to enforce the budget")
    assert not problems, "; ".join(problems)
