#!/usr/bin/env python3
"""Overload a staging tool runner until Kubernetes kills it, and check recovery.

Runs chat's own runner code (open_webui.utils.skill_k8s_sandbox) from a
laptop against the staging warm pool, for a throwaway chat id
(zz-overload-<hex>). It checks the three things a user depends on when a skill
uses too much memory:

1. The tool call fails with the out-of-memory message (OOM kill or memory
   eviction), not "runner may be overloaded" or "runner died".
2. The chat's files on JuiceFS survive the runner's death.
3. The chat gets a new runner quickly, and that runner sees the same files.

The memory hog grows until the kubelet stops it, so it puts the staging gVisor
node under memory pressure. The kubelet evicts the pod furthest over its
memory request first, which is the hog, but other runners on that node can be
slowed. Do not run it against prod. --yes is required.

Needs kubectl for rhiza-cluster and the backend's Python environment. It
imports open_webui from this checkout's backend/:

    python scripts/staging_runner_overload.py --yes
    python scripts/staging_runner_overload.py --yes --keep   # keep claim and files
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WRITER = """\
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import sys
from pathlib import Path

token = sys.argv[1]
Path("overload-canary.txt").write_text(token + "\\n")
chunks = Path("intermediate_results/overload-canary.zarr/c")
chunks.mkdir(parents=True, exist_ok=True)
for i in range(200):
    (chunks / str(i)).write_bytes(token.encode() * 64)
print(f"wrote {token}")
"""

READER = """\
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
from pathlib import Path

token = Path("overload-canary.txt").read_text().strip()
chunks = sorted(Path("intermediate_results/overload-canary.zarr/c").iterdir())
intact = all(p.read_bytes() == token.encode() * 64 for p in chunks)
print(f"token={token} chunks={len(chunks)} intact={intact}")
"""

# Grows by 256 MiB every 0.25 s, writing every page so the memory is really
# used, until the kubelet or the cgroup OOM killer stops it.
HOG = """\
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
import sys
import time

step = 256 * 1024 * 1024
limit = float(sys.argv[1]) * 1024**3
held, total = [], 0
while total < limit:
    block = bytearray(step)
    block[::4096] = b"\\x01" * (step // 4096)
    held.append(block)
    total += step
    print(f"holding {total / 1024**3:.2f} GiB", flush=True)
    time.sleep(0.25)
print("hog reached its limit without being stopped", flush=True)
"""

SAFE_TEST_CHAT = re.compile(r"^zz-overload-[0-9a-f]{8}$")
# This checkout's backend, not whichever open_webui the venv has installed.
BACKEND = Path(__file__).resolve().parents[1] / "backend"


def _setup_env(work: Path) -> Path:
    """Point chat at a scratch data dir before open_webui is imported."""
    os.environ.setdefault("DATA_DIR", str(work / "data"))
    skills = work / "skills"
    os.environ["SKILLS_DIR"] = str(skills)
    pack = skills / "zz-overload-pack" / "skills" / "overload"
    (pack / "scripts").mkdir(parents=True)
    for name, body in (("writer.py", WRITER), ("reader.py", READER), ("hog.py", HOG)):
        (pack / "scripts" / name).write_text(body)
    return pack


def _check(failures: list[str], ok: bool, what: str) -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {what}")
    if not ok:
        failures.append(what)


async def _run(k8s, chat_id: str, pack: Path, script: str, args: list[str], timeout: int) -> dict:
    return await k8s.run_skill_on_runner(
        chat_id=chat_id,
        skill_dir=pack,
        script_path=pack / "scripts" / script,
        args=args,
        env={},
        timeout=timeout,
    )


async def _ready_runner(k8s, chat_id: str, pack: Path) -> tuple[dict, float]:
    started = time.monotonic()
    info = await k8s.ensure_runner(chat_id)
    # A chat that is not in the database gets no packs at start; push ours.
    await k8s._ensure_pack_on_runner(info, pack)
    return info, time.monotonic() - started


def _juicefs_files(daemon: str, chat_id: str) -> list[str]:
    """The chat's files as the bind daemon sees them on JuiceFS, not via a runner."""
    out = subprocess.run(
        ["kubectl", "-n", os.environ.get("SKILL_K8S_SANDBOX_NAMESPACE", "weather-skills-sandbox-staging"),
         "exec", daemon, "-c", "daemon", "--", "find", f"/var/lib/juicefs/artifacts/{chat_id}", "-type", "f"],
        capture_output=True, text=True, check=False,
    )
    return sorted(line for line in out.stdout.splitlines() if line)


def _remove_test_files(daemon: str, chat_id: str) -> None:
    if not SAFE_TEST_CHAT.match(chat_id):
        raise ValueError(f"refusing to delete files of non-test chat {chat_id}")
    subprocess.run(
        ["kubectl", "-n", os.environ.get("SKILL_K8S_SANDBOX_NAMESPACE", "weather-skills-sandbox-staging"),
         "exec", daemon, "-c", "daemon", "--", "rm", "-rf", f"/var/lib/juicefs/artifacts/{chat_id}"],
        check=False,
    )


async def main(args: argparse.Namespace) -> int:
    work = Path(tempfile.mkdtemp(prefix="runner-overload-"))
    pack = _setup_env(work)
    sys.path.insert(0, str(BACKEND))
    from open_webui.utils import skill_k8s_sandbox as k8s

    chat_id = f"zz-overload-{secrets.token_hex(4)}"
    token = secrets.token_hex(8)
    failures: list[str] = []
    print(f"chat {chat_id} in {k8s._ns()}")

    info, took = await _ready_runner(k8s, chat_id, pack)
    first = info["pod_name"]
    daemon = await k8s._daemon_on_host(info["pod"]["status"]["hostIP"])
    print(f"runner {first} ready in {took:.1f}s (daemon {daemon})")

    try:
        wrote = await _run(k8s, chat_id, pack, "writer.py", [token], 120)
        _check(failures, wrote["ok"] and token in wrote["stdout"], "writer skill wrote the canary files")
        before = _juicefs_files(daemon, chat_id)
        print(f"  {len(before)} files on JuiceFS before the overload")

        print(f"overloading {first} (up to {args.gib} GiB) ...")
        started = time.monotonic()
        hog = await _run(k8s, chat_id, pack, "hog.py", [str(args.gib)], 600)
        print(f"  hog returned after {time.monotonic() - started:.0f}s")
        print(f"  stderr: {hog['stderr'][:400]}")
        _check(failures, not hog["ok"], "the overloading tool call failed")
        _check(
            failures,
            hog["stderr"].startswith("Tool call failed: the tool runner ran out of memory ("),
            "the model is told the runner ran out of memory",
        )

        after = _juicefs_files(daemon, chat_id)
        _check(failures, after == before, f"JuiceFS still has all {len(before)} files after the runner died")

        info, took = await _ready_runner(k8s, chat_id, pack)
        second = info["pod_name"]
        print(f"runner {second} ready in {took:.1f}s")
        _check(failures, second != first, "the chat got a new runner")
        _check(failures, took <= args.max_restart_seconds, f"the new runner was ready within {args.max_restart_seconds}s")

        read = await _run(k8s, chat_id, pack, "reader.py", [], 120)
        _check(
            failures,
            read["ok"] and f"token={token} chunks=200 intact=True" in read["stdout"],
            "the new runner sees the same files",
        )
    finally:
        if args.keep:
            print(f"kept claim {k8s.claim_name(chat_id)} and artifacts/{chat_id}")
        else:
            claim = await k8s.get_claim(chat_id)
            if claim:
                await k8s.delete_claim(chat_id, uid=(claim.get("metadata") or {}).get("uid"))
            _remove_test_files(daemon, chat_id)

    if failures:
        print(f"overload test FAILED: {len(failures)} check(s)")
        return 1
    print("overload test passed")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--yes", action="store_true", help="confirm: this puts a staging node under memory pressure")
    parser.add_argument("--gib", type=float, default=24, help="stop the hog here if nothing kills it (default 24)")
    parser.add_argument("--max-restart-seconds", type=float, default=90, help="new runner must be ready within this")
    parser.add_argument("--keep", action="store_true", help="leave the claim and the test chat's files")
    parsed = parser.parse_args()
    if not parsed.yes:
        parser.error("this overloads a staging gVisor node; pass --yes to run it")
    namespace = os.environ.get("SKILL_K8S_SANDBOX_NAMESPACE", "weather-skills-sandbox-staging")
    if not namespace.endswith("-staging"):
        parser.error(f"refusing to run outside a staging namespace (got {namespace})")
    sys.exit(asyncio.run(main(parsed)))
