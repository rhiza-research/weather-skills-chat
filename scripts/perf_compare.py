#!/usr/bin/env python3
"""Run the event-loop performance tests against git revisions and compare.

    python scripts/perf_compare.py 2d51fc3 HEAD
    python scripts/perf_compare.py --runs 3 origin/dev HEAD -- -k stream

Each revision is checked out into a temporary worktree. The tests in this
checkout's backend/perf run against that revision's app code, so every
revision faces the same scenarios. Budgets are not enforced, since an old
revision is expected to blow them. With --runs N each metric is the median.

Run with the Python environment the backend tests use (uv run, or .venv).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PERF_DIR = ROOT / "backend" / "perf"
METRICS = [("max_lag_ms", "max stall (ms)"), ("blocked_pct", "loop blocked (%)")]


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def run_revision(rev: str, runs: int, pytest_args: list[str]) -> tuple[str, dict]:
    label = git("log", "-1", "--format=%h %s", rev)
    rows: dict[str, list[dict]] = {}
    with tempfile.TemporaryDirectory(prefix="perf-") as tmp:
        tree = Path(tmp) / "tree"
        git("worktree", "add", "--detach", str(tree), rev)
        try:
            for run in range(runs):
                results = Path(tmp) / f"results-{run}.jsonl"
                env = {
                    **os.environ,
                    "PYTHONPATH": f"{tree / 'backend'}{os.pathsep}{tree / 'backend' / 'open_webui'}",
                    "PERF_RESULTS": str(results),
                    "PERF_REPORT_ONLY": "1",
                    "DATABASE_URL": f"sqlite:///{Path(tmp) / f'perf-{run}.db'}",
                }
                print(f"[{label}] run {run + 1}/{runs}", file=sys.stderr, flush=True)
                proc = subprocess.run(
                    [sys.executable, "-m", "pytest", str(PERF_DIR), "-q", "-p", "no:cacheprovider", *pytest_args],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                )
                if proc.returncode != 0:
                    print(proc.stdout[-3000:], file=sys.stderr)
                if results.exists():
                    for line in results.read_text().splitlines():
                        row = json.loads(line)
                        rows.setdefault(row["scenario"], []).append(row)
        finally:
            git("worktree", "remove", "--force", str(tree))
    medians = {
        scenario: {key: statistics.median(r[key] for r in found) for key, _ in METRICS}
        for scenario, found in rows.items()
    }
    return label, medians


def table(results: list[tuple[str, dict]]) -> str:
    scenarios = list(dict.fromkeys(s for _, found in results for s in found))
    labels = [label for label, _ in results]
    lines = ["Revisions:"] + [f"- **{chr(65 + i)}**: {label}" for i, label in enumerate(labels)] + [""]
    header = ["scenario"]
    for _, title in METRICS:
        header += [f"{title} {chr(65 + i)}" for i in range(len(results))]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "---|" * len(header))
    for scenario in scenarios:
        cells = [scenario]
        for key, _ in METRICS:
            for _, found in results:
                value = found.get(scenario, {}).get(key)
                cells.append("-" if value is None else f"{value:g}")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("revisions", nargs="+", help="git revisions, oldest first")
    parser.add_argument("--runs", type=int, default=1, help="runs per revision; metrics are medians")
    argv = sys.argv[1:]
    split = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:split])
    pytest_args = argv[split + 1 :]
    results = [run_revision(rev, args.runs, pytest_args) for rev in args.revisions]
    print(table(results))


if __name__ == "__main__":
    main()
