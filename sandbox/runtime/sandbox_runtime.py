#!/usr/bin/env python3
"""HTTP runtime inside a tool-runner pod: health, metrics, exec."""

from __future__ import annotations

import base64
import json
import os
import resource
import shlex
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PORT = int(os.environ.get("RUNTIME_PORT", "8888"))
WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
CGROUP = Path("/sys/fs/cgroup")
CPU_LIMIT = float(os.environ.get("SKILL_RUNNER_CPU_LIMIT", "3"))
MEMORY_LIMIT_GIB = float(os.environ.get("SKILL_RUNNER_MEMORY_LIMIT_GIB", "12"))
_LOG_LINES = 200
_LOG_CHARS = 400
_seen_quiet_paths: set[str] = set()


def log(message: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sys.stdout.write(f"{ts} {message}\n")
    sys.stdout.flush()


def skill_label(cmd: list[str]) -> str:
    if "--script" in cmd:
        idx = cmd.index("--script")
        if idx + 1 < len(cmd):
            parts = Path(cmd[idx + 1]).parts
            if "skills" in parts:
                i = parts.index("skills")
                if i + 1 < len(parts):
                    return parts[i + 1]
            if parts:
                return Path(parts[-1]).stem
    return cmd[0] if cmd else "?"


def _fmt_cmd(cmd: list[str]) -> str:
    text = shlex.join(cmd)
    return text if len(text) <= 500 else text[:500] + "…"


def _collect_and_log(proc: subprocess.Popen, timeout: int) -> tuple[str, str]:
    out_chunks: list[str] = []
    err_chunks: list[str] = []
    logged = {"stdout": 0, "stderr": 0}

    def pump(stream, chunks: list[str], name: str) -> None:
        if stream is None:
            return
        try:
            for line in stream:
                chunks.append(line)
                n = logged[name]
                if n < _LOG_LINES:
                    log(f"{name} {line.rstrip()[:_LOG_CHARS]}")
                    logged[name] = n + 1
                elif n == _LOG_LINES:
                    log(f"{name} … further {name} omitted")
                    logged[name] = n + 1
        except OSError:
            return

    threads = [
        threading.Thread(target=pump, args=(proc.stdout, out_chunks, "stdout"), daemon=True),
        threading.Thread(target=pump, args=(proc.stderr, err_chunks, "stderr"), daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        for thread in threads:
            thread.join(1)
        raise
    for thread in threads:
        thread.join()
    return "".join(out_chunks), "".join(err_chunks)


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def _cgroup_root() -> Path:
    raw = _read(Path("/proc/self/cgroup"))
    if raw:
        for line in raw.splitlines():
            if line.startswith("0::"):
                rel = line.split(":", 2)[-1].lstrip("/")
                candidate = CGROUP / rel if rel else CGROUP
                if (candidate / "cpu.stat").is_file() or (candidate / "memory.current").is_file():
                    return candidate
    return CGROUP


def _cpu_stat(root: Path) -> dict:
    cpu = _read(root / "cpu.stat")
    stats: dict = {}
    if cpu:
        for line in cpu.splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    stats[parts[0]] = float(parts[1])
                except ValueError:
                    pass
    if "usage_usec" not in stats:
        acct = _read(CGROUP / "cpuacct" / "cpuacct.usage")
        if acct and acct.isdigit():
            stats["usage_usec"] = int(acct) / 1000
    return stats


def _cgroup_memory_bytes(root: Path) -> int | None:
    mem = _read(root / "memory.current")
    if mem and mem.isdigit():
        return int(mem)
    legacy = _read(CGROUP / "memory" / "memory.usage_in_bytes")
    if legacy and legacy.isdigit():
        value = int(legacy)
        return value if value < 1 << 60 else None
    return None


def _sum_proc_cpu_usec() -> int | None:
    try:
        clk = os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError):
        return None
    total = 0
    found = False
    for path in Path("/proc").glob("*/stat"):
        try:
            parts = path.read_text().rsplit(")", 1)[-1].split()
            total += (int(parts[11]) + int(parts[12])) * 1_000_000 // clk
            found = True
        except (OSError, ValueError, IndexError):
            continue
    return total if found else None


def _sum_proc_rss() -> int | None:
    total = 0
    found = False
    for path in Path("/proc").glob("*/status"):
        try:
            for line in path.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1]) * 1024
                    found = True
                    break
        except (OSError, ValueError, IndexError):
            continue
    return total if found else None


def _rusage_fallback() -> tuple[int, int]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    cpu_usec = int((usage.ru_utime + usage.ru_stime) * 1_000_000)
    rss = usage.ru_maxrss
    memory = rss if sys.platform == "darwin" else rss * 1024
    return cpu_usec, memory


def collect_metrics() -> dict:
    root = _cgroup_root()
    cpu = _cpu_stat(root)
    memory = _cgroup_memory_bytes(root)
    peak = _read(root / "memory.peak")
    swap = _read(root / "memory.swap.current")
    if "usage_usec" not in cpu:
        proc_cpu = _sum_proc_cpu_usec()
        if proc_cpu is not None:
            cpu["usage_usec"] = proc_cpu
    if memory is None:
        memory = _sum_proc_rss()
    if "usage_usec" not in cpu or memory is None:
        fallback_cpu, fallback_mem = _rusage_fallback()
        cpu.setdefault("usage_usec", fallback_cpu)
        if memory is None:
            memory = fallback_mem
    metrics: dict = {
        "timestamp": time.time(),
        "cpu": cpu,
        "memory_bytes": memory,
        "cpu_limit": CPU_LIMIT,
        "memory_limit_bytes": int(MEMORY_LIMIT_GIB * 1024**3),
    }
    if peak and peak.isdigit():
        metrics["memory_peak_bytes"] = int(peak)
    if swap and swap.isdigit():
        metrics["memory_swap_current"] = int(swap)
    return metrics


def _unpack_roots() -> list[Path]:
    ws = WORKSPACE.resolve()
    roots = [ws]
    # Helm sets WORKSPACE=/workspace/chat (JuiceFS). Packs live on the emptyDir parent.
    if ws.name == "chat":
        roots.append(ws.parent)
    return roots


def _dest_allowed(dest: Path) -> bool:
    try:
        resolved = dest.resolve()
    except OSError:
        return False
    for root in _unpack_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def run_unpack(body: dict) -> dict:
    dest = Path(body.get("dest") or "")
    raw = body.get("archive") or ""
    started = time.monotonic()
    log(f"unpack start dest={dest} archive_b64_bytes={len(raw)}")
    if not dest.as_posix() or not _dest_allowed(dest):
        log(f"unpack reject dest={dest} error=invalid dest")
        return {"ok": False, "error": "invalid dest"}
    if dest.exists():
        log(f"unpack skip dest={dest} already present")
        return {"ok": True, "skipped": True}
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["tar", "-xz", "-C", str(dest.parent)],
            input=base64.b64decode(raw),
            check=True,
            capture_output=True,
        )
    except Exception as exc:
        log(f"unpack fail dest={dest} error={exc} elapsed={time.monotonic() - started:.2f}s")
        return {"ok": False, "error": str(exc)}
    log(f"unpack ok dest={dest} elapsed={time.monotonic() - started:.2f}s")
    return {"ok": True}


def run_exec(body: dict) -> dict:
    cmd = body.get("cmd") or []
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
        log("exec reject invalid cmd")
        return {"exit_code": 2, "stdout": "", "stderr": "invalid cmd"}
    cwd = body.get("cwd") or str(WORKSPACE)
    timeout = int(body.get("timeout") or 600)
    env = os.environ.copy()
    extra = body.get("env") or {}
    if isinstance(extra, dict):
        env.update({str(k): str(v) for k, v in extra.items()})
    label = skill_label(cmd)
    started = time.monotonic()
    log(f"exec start skill={label} cwd={cwd} timeout={timeout} cmd={_fmt_cmd(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = _collect_and_log(proc, timeout)
        elapsed = time.monotonic() - started
        log(
            f"exec done skill={label} exit={proc.returncode} elapsed={elapsed:.2f}s "
            f"stdout_bytes={len(stdout)} stderr_bytes={len(stderr)}"
        )
        return {
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
    except subprocess.TimeoutExpired:
        log(f"exec timeout skill={label} elapsed={timeout}s")
        return {"exit_code": -1, "stdout": "", "stderr": "timed out"}
    except Exception as exc:
        log(f"exec fail skill={label} error={exc} elapsed={time.monotonic() - started:.2f}s")
        return {"exit_code": 1, "stdout": "", "stderr": str(exc)}


class Handler(BaseHTTPRequestHandler):
    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            if path not in _seen_quiet_paths:
                _seen_quiet_paths.add(path)
                log("GET /health 204 (further health probes omitted)")
            self.send_response(204)
            self.end_headers()
            return
        if path == "/metrics":
            metrics = collect_metrics()
            if path not in _seen_quiet_paths:
                _seen_quiet_paths.add(path)
                log(
                    "GET /metrics 200 "
                    f"memory_bytes={metrics.get('memory_bytes')} "
                    f"(further metrics polls omitted)"
                )
            self._json(200, metrics)
            return
        log(f"GET {path} 404")
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/exec":
            log(f"POST /exec from={self.address_string()}")
            self._json(200, run_exec(self._read()))
            return
        if path == "/unpack":
            log(f"POST /unpack from={self.address_string()}")
            self._json(200, run_unpack(self._read()))
            return
        log(f"POST {path} 404")
        self._json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    log(
        "startup"
        f" workspace={WORKSPACE}"
        f" port={PORT}"
        f" uid={os.getuid()}"
        f" host={socket.gethostname()}"
        f" python={sys.version.split()[0]}"
        f" cpu_limit={CPU_LIMIT}"
        f" memory_limit_gib={MEMORY_LIMIT_GIB}"
    )
    try:
        uv = subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=5)
        log(f"startup uv={(uv.stdout or uv.stderr).strip() or 'unknown'}")
    except Exception as exc:
        log(f"startup uv unavailable: {exc}")
    log(f"listening 0.0.0.0:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
