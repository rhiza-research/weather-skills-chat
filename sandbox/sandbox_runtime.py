#!/usr/bin/env python3
"""HTTP runtime inside a tool-runner pod: health, metrics, exec."""

from __future__ import annotations

import json
import os
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

PORT = int(os.environ.get("RUNTIME_PORT", "8888"))
WORKSPACE = Path(os.environ.get("WORKSPACE", "/workspace"))
CGROUP = Path("/sys/fs/cgroup")


def _read(path: Path) -> str | None:
    try:
        return path.read_text().strip()
    except OSError:
        return None


def collect_metrics() -> dict:
    metrics: dict = {"timestamp": time.time()}
    cpu = _read(CGROUP / "cpu.stat")
    if cpu:
        stats = {}
        for line in cpu.splitlines():
            parts = line.split()
            if len(parts) == 2:
                try:
                    stats[parts[0]] = float(parts[1])
                except ValueError:
                    pass
        metrics["cpu"] = stats
    mem = _read(CGROUP / "memory.current")
    if mem and mem.isdigit():
        metrics["memory_bytes"] = int(mem)
    peak = _read(CGROUP / "memory.peak")
    if peak and peak.isdigit():
        metrics["memory_peak_bytes"] = int(peak)
    swap = _read(CGROUP / "memory.swap.current")
    if swap and swap.isdigit():
        metrics["memory_swap_current"] = int(swap)
    return metrics


def run_exec(body: dict) -> dict:
    cmd = body.get("cmd") or []
    if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
        return {"exit_code": 2, "stdout": "", "stderr": "invalid cmd"}
    cwd = body.get("cwd") or str(WORKSPACE)
    env = os.environ.copy()
    extra = body.get("env") or {}
    if isinstance(extra, dict):
        env.update({str(k): str(v) for k, v in extra.items()})
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=int(body.get("timeout") or 600),
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"exit_code": -1, "stdout": "", "stderr": "timed out"}
    except Exception as exc:
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
            self.send_response(204)
            self.end_headers()
            return
        if path == "/metrics":
            self._json(200, collect_metrics())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/exec":
            self._json(200, run_exec(self._read()))
            return
        self._json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args) -> None:
        return


def main() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
