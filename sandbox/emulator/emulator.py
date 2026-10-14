# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#!/usr/bin/env python3
"""Local stand-in for the GKE Agent Sandbox API + bind daemon + runner.

No gVisor, no JuiceFS, no isolation. Chat talks to this the same way it talks
to the cluster: SandboxClaim on a fake apiserver, bind/own on :9090, exec on the
per-chat runtime. The runner cwd is the chat's artifacts directory.

    uv run --script sandbox/emulator/emulator.py

Then start the backend with:

    SKILL_SANDBOX_BACKEND=k8s
    SKILL_K8S_SANDBOX_ENABLED=true
    SKILL_K8S_EMULATOR=true
    SKILL_K8S_BIND_TOKEN=dev
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
RUNTIME = HERE / "local_runtime.py"
TOKEN = os.environ.get("SKILL_K8S_BIND_TOKEN", "dev")
API_PORT = int(os.environ.get("SKILL_K8S_EMULATOR_API_PORT", "18080"))
BIND_PORT = int(os.environ.get("SKILL_K8S_BIND_PORT", "9090"))
RUNNER_PORT0 = int(os.environ.get("SKILL_K8S_EMULATOR_RUNNER_PORT", "18888"))
NS = os.environ.get("SKILL_K8S_SANDBOX_NAMESPACE", "weather-skills-sandbox-staging")
API_GROUP = os.environ.get("SKILL_K8S_SANDBOX_API_GROUP", "extensions.agents.x-k8s.io")
API_VERSION = os.environ.get("SKILL_K8S_SANDBOX_API_VERSION", "v1beta1")


_local_runtime = None


def _process_metrics() -> dict:
    global _local_runtime
    if _local_runtime is None:
        spec = importlib.util.spec_from_file_location("local_runtime", HERE / "local_runtime.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _local_runtime = module
    return _local_runtime.collect_metrics()


def _host() -> str:
    return os.environ.get("SKILL_K8S_EMULATOR_HOST", "127.0.0.1").strip() or "127.0.0.1"


def _artifacts() -> Path:
    raw = os.environ.get("ARTIFACTS_DIR", "").strip()
    if raw:
        return Path(raw)
    data = Path(os.environ.get("DATA_DIR") or "backend/data")
    return data / "artifacts"


_lock = threading.Lock()
_claims: dict[str, dict] = {}
_pods: dict[str, dict] = {}
_procs: dict[str, subprocess.Popen] = {}
_next_port = RUNNER_PORT0


def _json(handler: BaseHTTPRequestHandler, code: int, body: dict | list) -> None:
    data = json.dumps(body).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _read(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if not length:
        return {}
    return json.loads(handler.rfile.read(length))


def _workspace(chat_id: str) -> Path:
    path = _artifacts() / chat_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _start_runtime(chat_id: str, port: int) -> None:
    workspace = _workspace(chat_id)
    env = os.environ.copy()
    env["WORKSPACE"] = str(workspace)
    env["RUNTIME_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, str(RUNTIME)],
        env=env,
        cwd=str(workspace),
    )
    _procs[chat_id] = proc
    deadline = time.time() + 8
    import urllib.error
    import urllib.request

    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"sandbox_runtime exited {proc.returncode}")
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.3)
            return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.1)
    raise RuntimeError("sandbox_runtime did not become ready")


def _stop_runtime(chat_id: str) -> None:
    proc = _procs.pop(chat_id, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _make_pod(chat_id: str, port: int) -> dict:
    name = f"local-runner-{chat_id}"[:63]
    uid = str(uuid.uuid4())
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": NS,
            "uid": uid,
            "labels": {"weather-skills-tool-runner": "true"},
            "annotations": {},
        },
        "spec": {
            "containers": [
                {
                    "name": "runner",
                    "ports": [
                        {
                            "name": "runtime",
                            "containerPort": port,
                            "hostPort": port,
                        }
                    ],
                }
            ]
        },
        "status": {
            "phase": "Running",
            "podIP": _host(),
            "hostIP": _host(),
        },
    }


def _start_delay() -> float:
    raw = os.environ.get("SKILL_K8S_EMULATOR_START_DELAY", "0").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def _make_claim(chat_id: str, name: str, pod_name: str, *, ready: bool = True) -> dict:
    return {
        "apiVersion": f"{API_GROUP}/{API_VERSION}",
        "kind": "SandboxClaim",
        "metadata": {
            "name": name,
            "namespace": NS,
            "labels": {"weather-skills-chat": chat_id},
            "finalizers": ["agent.sandbox/storage-cleanup"],
        },
        "spec": {"warmPoolRef": {"name": "local"}},
        "status": {
            "ready": ready,
            "sandbox": {"name": pod_name},
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
        },
    }


def _finish_start(chat_id: str, port: int) -> None:
    try:
        _start_runtime(chat_id, port)
    except Exception as exc:
        sys.stderr.write(f"runtime start failed for {chat_id}: {exc}\n")
        return
    with _lock:
        claim = _claims.get(chat_id)
        if not claim:
            _stop_runtime(chat_id)
            return
        claim["status"]["ready"] = True
        claim["status"]["conditions"] = [{"type": "Ready", "status": "True"}]


class ApiHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        claims_root = f"/apis/{API_GROUP}/{API_VERSION}/namespaces/{NS}/sandboxclaims"
        pods_root = f"/api/v1/namespaces/{NS}/pods"
        secrets_root = f"/api/v1/namespaces/{NS}/secrets"
        with _lock:
            if path == claims_root:
                _json(self, 200, {"items": list(_claims.values())})
                return
            if path.startswith(claims_root + "/"):
                name = path.rsplit("/", 1)[-1]
                for claim in _claims.values():
                    if claim["metadata"]["name"] == name:
                        _json(self, 200, claim)
                        return
                _json(self, 404, {"reason": "NotFound"})
                return
            if path == pods_root:
                items = list(_pods.values())
                selector = (query.get("labelSelector") or [""])[0]
                if "daemon" in selector:
                    items = [
                        {
                            "metadata": {"name": "local-bind-daemon"},
                            "status": {"hostIP": _host(), "podIP": _host()},
                            "spec": {"nodeName": "local"},
                        }
                    ]
                _json(self, 200, {"items": items})
                return
            if path.startswith(pods_root + "/"):
                name = path.rsplit("/", 1)[-1]
                pod = _pods.get(name)
                if not pod:
                    for item in _pods.values():
                        if item["metadata"]["name"] == name:
                            pod = item
                            break
                if pod:
                    _json(self, 200, pod)
                    return
                _json(self, 404, {"reason": "NotFound"})
                return
            if path == secrets_root:
                token = base64_token()
                _json(
                    self,
                    200,
                    {
                        "items": [
                            {
                                "metadata": {"name": "local-daemon"},
                                "data": {"token": token, "metaurl": token},
                            }
                        ]
                    },
                )
                return
        _json(self, 404, {"reason": "NotFound"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = _read(self)
        claims_root = f"/apis/{API_GROUP}/{API_VERSION}/namespaces/{NS}/sandboxclaims"
        if path != claims_root:
            _json(self, 404, {"reason": "NotFound"})
            return
        chat_id = (body.get("metadata") or {}).get("labels", {}).get(
            "weather-skills-chat"
        ) or body["metadata"]["name"]
        name = body["metadata"]["name"]
        with _lock:
            if any(c["metadata"]["name"] == name for c in _claims.values()):
                _json(self, 409, {"reason": "AlreadyExists"})
                return
            global _next_port
            port = _next_port
            _next_port += 1
            pod = _make_pod(chat_id, port)
            _pods[pod["metadata"]["name"]] = pod
            delay = _start_delay()
            _claims[chat_id] = _make_claim(
                chat_id, name, pod["metadata"]["name"], ready=(delay <= 0)
            )
        if delay <= 0:
            _start_runtime(chat_id, port)
        else:
            threading.Timer(delay, _finish_start, args=(chat_id, port)).start()
        _json(self, 201, _claims[chat_id])

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = _read(self)
        claims_root = f"/apis/{API_GROUP}/{API_VERSION}/namespaces/{NS}/sandboxclaims/"
        if not path.startswith(claims_root):
            _json(self, 404, {"reason": "NotFound"})
            return
        name = path.rsplit("/", 1)[-1]
        with _lock:
            for chat_id, claim in _claims.items():
                if claim["metadata"]["name"] == name:
                    body.setdefault("status", claim.get("status"))
                    _claims[chat_id] = body
                    _json(self, 200, body)
                    return
        _json(self, 404, {"reason": "NotFound"})

    def do_PATCH(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = _read(self)
        pods_root = f"/api/v1/namespaces/{NS}/pods/"
        if not path.startswith(pods_root):
            _json(self, 404, {"reason": "NotFound"})
            return
        name = path.rsplit("/", 1)[-1]
        with _lock:
            pod = _pods.get(name)
            if not pod:
                _json(self, 404, {"reason": "NotFound"})
                return
            anns = (pod.setdefault("metadata", {})).setdefault("annotations", {})
            anns.update(((body.get("metadata") or {}).get("annotations")) or {})
            _json(self, 200, pod)

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        claims_root = f"/apis/{API_GROUP}/{API_VERSION}/namespaces/{NS}/sandboxclaims/"
        if not path.startswith(claims_root):
            _json(self, 404, {"reason": "NotFound"})
            return
        name = path.rsplit("/", 1)[-1]
        with _lock:
            chat_id = None
            for cid, claim in list(_claims.items()):
                if claim["metadata"]["name"] == name:
                    chat_id = cid
                    pod_name = (claim.get("status") or {}).get("sandbox", {}).get("name")
                    _claims.pop(cid)
                    if pod_name:
                        _pods.pop(pod_name, None)
                    break
        if chat_id:
            _stop_runtime(chat_id)
            _json(self, 200, {})
            return
        _json(self, 404, {"reason": "NotFound"})


def base64_token() -> str:
    import base64

    return base64.b64encode(TOKEN.encode()).decode()


class BindHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _auth(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {TOKEN}"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            _json(self, 200, {"ok": True})
            return
        if parsed.path == "/metrics":
            if not self._auth():
                _json(self, 401, {"error": "unauthorized"})
                return
            _json(self, 200, _process_metrics())
            return
        _json(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._auth():
            _json(self, 401, {"error": "unauthorized"})
            return
        path = urlparse(self.path).path
        body = _read(self)
        if path in ("/bind", "/quota", "/unbind", "/own"):
            if path == "/bind":
                _workspace(body.get("chat_id") or "")
            _json(self, 200, {"ok": True})
            return
        _json(self, 404, {"error": "not found"})


def main() -> None:
    if not RUNTIME.is_file():
        raise SystemExit(f"missing {RUNTIME}")
    listen = "0.0.0.0" if _host() not in ("127.0.0.1", "localhost") else "127.0.0.1"
    api = ThreadingHTTPServer((listen, API_PORT), ApiHandler)
    bind = ThreadingHTTPServer((listen, BIND_PORT), BindHandler)
    threading.Thread(target=bind.serve_forever, daemon=True).start()
    sys.stderr.write(
        f"emulator apiserver http://{listen}:{API_PORT} "
        f"bind :{BIND_PORT} advertise={_host()} artifacts={_artifacts()}\n"
    )
    try:
        api.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for chat_id in list(_procs):
            _stop_runtime(chat_id)
        api.server_close()
        bind.shutdown()


if __name__ == "__main__":
    main()
