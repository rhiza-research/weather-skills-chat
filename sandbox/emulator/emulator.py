# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
#!/usr/bin/env python3
"""Local stand-in for the GKE Agent Sandbox API + bind daemon + runner.

No gVisor, no JuiceFS, no isolation. Chat talks to this the same way it talks
to the cluster: SandboxClaim on a fake apiserver, bind/own on :9090, exec on the
per-chat runtime. The runner cwd is the chat's artifacts directory.

It serves the same runner sizes as the cluster (RUNNER_TYPES, mirroring
`runners` in the infrastructure chart's values.yaml) as SandboxTemplates. A
claim of a size with no warm pool takes longer to be ready, and its metrics
report that size's limits; nothing enforces them.

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


CATALOG_PREFIX = "weather-skills.org"
TYPE_LABEL = f"{CATALOG_PREFIX}/runner-type"
CLAIM_TYPE_LABEL = "weather-skills-runner-type"

# The cluster's runner sizes (infrastructure charts/weather-skills-sandbox
# values.yaml runners). SKILL_K8S_EMULATOR_RUNNER_TYPES (JSON, same keys)
# replaces them.
RUNNER_TYPES = {
    "standard": {
        "name": "weather-skills-standard-runner",
        "displayName": "Standard",
        "description": "Shared runner for everyday skills.",
        "order": 1,
        "warmPool": 2,
        "startTimeoutSeconds": 120,
        "idleTtlSeconds": 600,
        "requiresApproval": False,
        "limits": {"cpu": "8", "memory": "8Gi"},
    },
    "medium": {
        "name": "weather-skills-medium-runner",
        "displayName": "Medium",
        "description": "Twice the standard memory limit and more guaranteed CPU, for larger regions or longer periods.",
        "order": 2,
        "warmPool": 0,
        "startTimeoutSeconds": 300,
        "idleTtlSeconds": 600,
        "requiresApproval": False,
        "limits": {"cpu": "8", "memory": "16Gi"},
    },
    "large": {
        "name": "weather-skills-large-runner",
        "displayName": "Large",
        "description": "A whole 8-CPU, 64 GB machine. Takes about 2 minutes to start.",
        "order": 3,
        "warmPool": 0,
        "startTimeoutSeconds": 300,
        "idleTtlSeconds": 300,
        "requiresApproval": True,
        "limits": {"cpu": "8", "memory": "52Gi"},
    },
    "xlarge": {
        "name": "weather-skills-xlarge-runner",
        "displayName": "XLarge",
        "description": "A whole 16-CPU, 128 GB machine. Takes about 2 minutes to start.",
        "order": 4,
        "warmPool": 0,
        "startTimeoutSeconds": 300,
        "idleTtlSeconds": 300,
        "requiresApproval": True,
        "limits": {"cpu": "16", "memory": "108Gi"},
    },
}


def _runner_types() -> dict:
    raw = os.environ.get("SKILL_K8S_EMULATOR_RUNNER_TYPES", "").strip()
    if not raw:
        return RUNNER_TYPES
    try:
        parsed = json.loads(raw)
    except ValueError:
        sys.stderr.write("SKILL_K8S_EMULATOR_RUNNER_TYPES is not JSON; using the built-in sizes\n")
        return RUNNER_TYPES
    return parsed if isinstance(parsed, dict) and parsed else RUNNER_TYPES


def _template(rtype: str, spec: dict) -> dict:
    return {
        "apiVersion": f"{API_GROUP}/{API_VERSION}",
        "kind": "SandboxTemplate",
        "metadata": {
            "name": spec["name"],
            "namespace": NS,
            "labels": {TYPE_LABEL: rtype},
            "annotations": {
                f"{CATALOG_PREFIX}/display-name": str(spec.get("displayName") or rtype),
                f"{CATALOG_PREFIX}/description": str(spec.get("description") or ""),
                f"{CATALOG_PREFIX}/order": str(spec.get("order", 0)),
                f"{CATALOG_PREFIX}/warm": str(int(spec.get("warmPool") or 0) > 0).lower(),
                f"{CATALOG_PREFIX}/start-timeout-seconds": str(spec.get("startTimeoutSeconds", 300)),
                f"{CATALOG_PREFIX}/idle-ttl-seconds": str(spec.get("idleTtlSeconds", 600)),
                f"{CATALOG_PREFIX}/requires-approval": str(bool(spec.get("requiresApproval"))).lower(),
            },
        },
        "spec": {
            "podTemplate": {
                "spec": {
                    "containers": [
                        {"name": "runner", "resources": {"limits": dict(spec.get("limits") or {})}}
                    ]
                }
            }
        },
    }


def _templates() -> list[dict]:
    return [_template(rtype, spec) for rtype, spec in _runner_types().items()]


def _spec_for_pool(pool: str) -> tuple[str, dict]:
    """(type, spec) of the size whose warm pool is `pool`; the first size if none matches."""
    sizes = _runner_types()
    for rtype, spec in sizes.items():
        if spec.get("name") == pool:
            return rtype, spec
    rtype = next(iter(sizes))
    return rtype, sizes[rtype]


def _cpu(quantity) -> float:
    raw = str(quantity or "").strip()
    if raw.endswith("m"):
        return float(raw[:-1]) / 1000
    return float(raw) if raw else 0.0


def _bytes(quantity) -> int:
    raw = str(quantity or "").strip()
    for suffix, scale in (("Ki", 2**10), ("Mi", 2**20), ("Gi", 2**30), ("Ti", 2**40)):
        if raw.endswith(suffix):
            return int(float(raw[: -len(suffix)]) * scale)
    return int(float(raw)) if raw else 0


def _matches(labels: dict, selector: str) -> bool:
    """A Kubernetes label selector of `key=value` and bare `key` terms."""
    for term in (t.strip() for t in selector.split(",") if t.strip()):
        if "=" in term:
            key, value = term.split("=", 1)
            if labels.get(key.rstrip("=")) != value:
                return False
        elif term not in labels:
            return False
    return True


_lock = threading.Lock()
# By claim name: a chat can hold claims of two sizes while it switches.
_claims: dict[str, dict] = {}
_pods: dict[str, dict] = {}
_procs: dict[str, subprocess.Popen] = {}
# Exit code of a claim's runtime after it stopped, until a new one starts:
# lets a pod read show a terminated container, as on the cluster.
_exit_codes: dict[str, int] = {}
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


def _start_runtime(key: str, chat_id: str, port: int) -> None:
    workspace = _workspace(chat_id)
    env = os.environ.copy()
    env["WORKSPACE"] = str(workspace)
    env["RUNTIME_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, str(RUNTIME)],
        env=env,
        cwd=str(workspace),
    )
    _procs[key] = proc
    _exit_codes.pop(key, None)
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


def _stop_runtime(key: str) -> None:
    proc = _procs.pop(key, None)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    if proc:
        _exit_codes[key] = proc.poll() if proc.poll() is not None else -9


def _make_pod(chat_id: str, port: int, key: str = "", rtype: str = "standard") -> dict:
    """The runner pod of claim `key`; the claim name keeps two sizes apart."""
    name = f"local-{key or chat_id}"[:63]
    uid = str(uuid.uuid4())
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "namespace": NS,
            "uid": uid,
            "labels": {
                "weather-skills-tool-runner": "true",
                "weather-skills-chat": chat_id,
                "weather-skills-runner-type": rtype,
                "weather-skills-claim": key or chat_id,
            },
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


def _pod_view(pod: dict) -> dict:
    """The pod with its runner container's state, as the cluster reports it:
    running while the runtime process lives, terminated once it has died."""
    labels = (pod.get("metadata") or {}).get("labels") or {}
    key = labels.get("weather-skills-claim") or labels.get("weather-skills-chat")
    proc = _procs.get(key) if key else None
    if proc is None:
        if key not in _exit_codes:
            return pod
        code = _exit_codes[key]
    else:
        code = proc.poll()
    if code is None:
        state = {"running": {}}
    else:
        state = {"terminated": {"reason": "Error", "exitCode": code}}
    view = dict(pod)
    view["status"] = {
        **(pod.get("status") or {}),
        "containerStatuses": [{"name": "runner", "ready": code is None, "state": state}],
    }
    return view


def _seconds_env(name: str, default: str = "0") -> float:
    raw = os.environ.get(name, default).strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 0.0


def _start_delay(spec: dict | None = None) -> float:
    """Seconds before a new claim is ready. A size with no warm pool uses
    SKILL_K8S_EMULATOR_COLD_START_DELAY (default: the warm delay)."""
    warm = _seconds_env("SKILL_K8S_EMULATOR_START_DELAY")
    if spec is not None and int(spec.get("warmPool") or 0) <= 0:
        cold = os.environ.get("SKILL_K8S_EMULATOR_COLD_START_DELAY", "").strip()
        if cold:
            return _seconds_env("SKILL_K8S_EMULATOR_COLD_START_DELAY")
    return warm


def _make_claim(
    chat_id: str,
    name: str,
    pod_name: str,
    *,
    ready: bool = True,
    labels: dict | None = None,
    pool: str = "local",
) -> dict:
    return {
        "apiVersion": f"{API_GROUP}/{API_VERSION}",
        "kind": "SandboxClaim",
        "metadata": {
            "name": name,
            "namespace": NS,
            "labels": {**(labels or {}), "weather-skills-chat": chat_id},
            "finalizers": ["agent.sandbox/storage-cleanup"],
            "uid": str(uuid.uuid4()),
        },
        "spec": {"warmPoolRef": {"name": pool}},
        "status": {
            "ready": ready,
            "sandbox": {"name": pod_name},
            "conditions": [{"type": "Ready", "status": "True" if ready else "False"}],
        },
    }


def _finish_start(key: str, chat_id: str, port: int) -> None:
    try:
        _start_runtime(key, chat_id, port)
    except Exception as exc:
        sys.stderr.write(f"runtime start failed for {key}: {exc}\n")
        return
    with _lock:
        claim = _claims.get(key)
        if not claim:
            _stop_runtime(key)
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
        templates_root = f"/apis/{API_GROUP}/{API_VERSION}/namespaces/{NS}/sandboxtemplates"
        selector = (query.get("labelSelector") or [""])[0]
        if path == templates_root:
            items = [t for t in _templates() if _matches(t["metadata"]["labels"], selector)]
            _json(self, 200, {"items": items})
            return
        if path.startswith(templates_root + "/"):
            name = path.rsplit("/", 1)[-1]
            for template in _templates():
                if template["metadata"]["name"] == name:
                    _json(self, 200, template)
                    return
            _json(self, 404, {"reason": "NotFound"})
            return
        with _lock:
            if path == claims_root:
                items = [
                    c for c in _claims.values() if _matches(c["metadata"].get("labels") or {}, selector)
                ]
                _json(self, 200, {"items": items})
                return
            if path.startswith(claims_root + "/"):
                name = path.rsplit("/", 1)[-1]
                claim = _claims.get(name)
                if claim:
                    _json(self, 200, claim)
                    return
                _json(self, 404, {"reason": "NotFound"})
                return
            if path == pods_root:
                items = list(_pods.values())
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
                    _json(self, 200, _pod_view(pod))
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
        labels = (body.get("metadata") or {}).get("labels") or {}
        chat_id = labels.get("weather-skills-chat") or body["metadata"]["name"]
        name = body["metadata"]["name"]
        pool = ((body.get("spec") or {}).get("warmPoolRef") or {}).get("name") or ""
        rtype, spec = _spec_for_pool(pool)
        with _lock:
            if name in _claims:
                _json(self, 409, {"reason": "AlreadyExists"})
                return
            global _next_port
            port = _next_port
            _next_port += 1
            pod = _make_pod(chat_id, port, key=name, rtype=rtype)
            _pods[pod["metadata"]["name"]] = pod
            delay = _start_delay(spec)
            _exit_codes.pop(name, None)
            _claims[name] = _make_claim(
                chat_id,
                name,
                pod["metadata"]["name"],
                ready=(delay <= 0),
                labels=labels,
                pool=pool or "local",
            )
            claim = _claims[name]
        sys.stderr.write(f"claim {name} size={rtype} ready in {delay:.0f}s\n")
        if delay <= 0:
            _start_runtime(name, chat_id, port)
        else:
            threading.Timer(delay, _finish_start, args=(name, chat_id, port)).start()
        _json(self, 201, claim)

    def do_PUT(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = _read(self)
        claims_root = f"/apis/{API_GROUP}/{API_VERSION}/namespaces/{NS}/sandboxclaims/"
        if not path.startswith(claims_root):
            _json(self, 404, {"reason": "NotFound"})
            return
        name = path.rsplit("/", 1)[-1]
        with _lock:
            claim = _claims.get(name)
            if claim:
                body.setdefault("status", claim.get("status"))
                _claims[name] = body
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
        # DeleteOptions.preconditions.uid, as on the cluster: a delete aimed
        # at an older claim must not remove its same-named replacement.
        want_uid = ((_read(self).get("preconditions") or {}).get("uid")) or None
        with _lock:
            claim = _claims.get(name)
            if claim is not None:
                if want_uid and claim["metadata"].get("uid") != want_uid:
                    _json(self, 409, {"reason": "Conflict"})
                    return
                pod_name = (claim.get("status") or {}).get("sandbox", {}).get("name")
                _claims.pop(name)
                if pod_name:
                    _pods.pop(pod_name, None)
        if claim is not None:
            sys.stderr.write(f"claim {name} released\n")
            _stop_runtime(name)
            _json(self, 200, {})
            return
        _json(self, 404, {"reason": "NotFound"})


def _pod_metrics(pod_uid: str) -> dict:
    """This process's CPU and memory, with the limits of the pod's size."""
    metrics = _process_metrics()
    with _lock:
        pod = next((p for p in _pods.values() if p["metadata"].get("uid") == pod_uid), None)
    if pod is None:
        return metrics
    rtype = (pod["metadata"].get("labels") or {}).get("weather-skills-runner-type")
    limits = (_runner_types().get(rtype) or {}).get("limits") or {}
    if limits.get("cpu"):
        metrics["cpu_limit"] = _cpu(limits["cpu"])
    if limits.get("memory"):
        metrics["memory_limit_bytes"] = _bytes(limits["memory"])
    return metrics


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
            uid = (parse_qs(parsed.query).get("pod_uid") or [""])[0]
            _json(self, 200, _pod_metrics(uid))
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
        for key in list(_procs):
            _stop_runtime(key)
        api.server_close()
        bind.shutdown()


if __name__ == "__main__":
    main()
