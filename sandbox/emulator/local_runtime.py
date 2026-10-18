"""Start the real sandbox runtime with process-level /metrics.

The pod runtime reads Linux cgroups. This wrapper is only for the laptop
emulator: same /health and /exec, but CPU and RSS come from this process.
"""

from __future__ import annotations

import importlib.util
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The runner runtime lives in rhiza-research/infrastructure
# (images/sandbox-runner) and is installed at this path in the runner image.
# Outside that image, point SANDBOX_RUNTIME_PATH at a checkout's copy.
RUNTIME = Path(os.environ.get("SANDBOX_RUNTIME_PATH", "/usr/local/bin/sandbox_runtime.py"))


def collect_metrics() -> dict:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    cpu_usec = (usage.ru_utime + usage.ru_stime) * 1_000_000
    statm = Path("/proc/self/statm")
    memory_bytes = 0
    if statm.is_file():
        parts = statm.read_text().split()
        if len(parts) >= 2 and parts[1].isdigit():
            memory_bytes = int(parts[1]) * os.sysconf("SC_PAGE_SIZE")
    if not memory_bytes:
        try:
            out = subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(os.getpid())],
                text=True,
            )
            memory_bytes = int(out.strip().split()[0]) * 1024
        except (OSError, ValueError, IndexError):
            rss = usage.ru_maxrss
            memory_bytes = rss if sys.platform == "darwin" else rss * 1024
    return {
        "timestamp": time.time(),
        "cpu": {"usage_usec": cpu_usec},
        "memory_bytes": memory_bytes,
        "cpu_limit": float(os.environ.get("SKILL_RUNNER_CPU_LIMIT", "3")),
        "memory_limit_bytes": int(
            float(os.environ.get("SKILL_RUNNER_MEMORY_LIMIT_GIB", "12")) * 1024**3
        ),
    }


CHAT_PREFIX = "/workspace/chat"
UV_CACHE_PREFIX = "/workspace/.uv-cache"
PACKS_PREFIX = "/workspace/.skill-packs"


def map_workspace_path(value: str, workspace: str | None = None) -> str:
    """Chat sends /workspace/chat; the emulator's real dir is WORKSPACE."""
    root = workspace if workspace is not None else os.environ.get("WORKSPACE", "/workspace")
    if value == CHAT_PREFIX:
        return root
    if value.startswith(CHAT_PREFIX + "/"):
        return root + value[len(CHAT_PREFIX) :]
    cache_root = str(Path(root).parent / ".uv-cache")
    if value == UV_CACHE_PREFIX:
        return cache_root
    if value.startswith(UV_CACHE_PREFIX + "/"):
        return cache_root + value[len(UV_CACHE_PREFIX) :]
    packs_root = str(Path(root) / ".skill-packs")
    if value == PACKS_PREFIX:
        return packs_root
    if value.startswith(PACKS_PREFIX + "/"):
        return packs_root + value[len(PACKS_PREFIX) :]
    return value


def remap_exec_body(body: dict, workspace: str | None = None) -> dict:
    out = dict(body)
    cwd = out.get("cwd")
    if isinstance(cwd, str):
        out["cwd"] = map_workspace_path(cwd, workspace)
    cmd = out.get("cmd")
    if isinstance(cmd, list):
        out["cmd"] = [
            map_workspace_path(part, workspace) if isinstance(part, str) else part
            for part in cmd
        ]
    extra = out.get("env")
    if isinstance(extra, dict):
        out["env"] = {
            key: map_workspace_path(val, workspace) if isinstance(val, str) else val
            for key, val in extra.items()
        }
    return out


def main() -> None:
    spec = importlib.util.spec_from_file_location("sandbox_runtime", RUNTIME)
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    runtime.collect_metrics = collect_metrics
    orig_exec = runtime.run_exec
    orig_unpack = runtime.run_unpack

    def run_exec(body: dict, **kwargs) -> dict:
        # kwargs: what the runtime's handler passes along, such as gone (the
        # caller hung up), which newer runtimes use to stop the skill.
        return orig_exec(remap_exec_body(body), **kwargs)

    def run_unpack(body: dict) -> dict:
        out = dict(body)
        dest = out.get("dest")
        if isinstance(dest, str):
            out["dest"] = map_workspace_path(dest)
        return orig_unpack(out)

    runtime.run_exec = run_exec
    runtime.run_unpack = run_unpack
    runtime.main()


if __name__ == "__main__":
    if not RUNTIME.is_file():
        raise SystemExit(
            f"missing {RUNTIME}: set SANDBOX_RUNTIME_PATH to sandbox_runtime.py from "
            "rhiza-research/infrastructure images/sandbox-runner"
        )
    main()
