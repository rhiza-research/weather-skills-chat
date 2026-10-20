"""Per-chat tool runner on GKE Agent Sandbox (claim, bind, own, exec, metrics).

In-cluster (the chat pod) talks to the API with the service-account token and
reaches the bind daemon / runner over the pod network. From a laptop the same
functions use kubectl proxy + port-forward. Config is the SKILL_K8S_* env vars
the chat Helm chart already sets.
"""

from __future__ import annotations

import asyncio
import atexit
import base64
import contextlib
import io
import json
import logging
import math
import os
import re
import ssl
import subprocess
import tarfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import aiohttp

log = logging.getLogger(__name__)

SA = Path("/var/run/secrets/kubernetes.io/serviceaccount")
FINALIZER = "agent.sandbox/storage-cleanup"
DAEMON_LABEL = "app.kubernetes.io/component=daemon"

_lock = threading.Lock()
_proxy_url: Optional[str] = None
_forward_urls: dict[tuple[str, int], str] = {}
_children: list[subprocess.Popen] = []
_bind_token: Optional[str] = None
_ready_cache: dict[str, tuple[float, dict]] = {}
_starts: dict[str, asyncio.Task] = {}


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int_env(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _ns() -> str:
    return _env("SKILL_K8S_SANDBOX_NAMESPACE", "weather-skills-sandbox-staging")


def _pool() -> str:
    return _env("SKILL_K8S_SANDBOX_POOL", "weather-skills-standard-runner")


def _api_group() -> str:
    return _env("SKILL_K8S_SANDBOX_API_GROUP", "extensions.agents.x-k8s.io")


def _api_version() -> str:
    return _env("SKILL_K8S_SANDBOX_API_VERSION", "v1beta1")


def _bind_port() -> int:
    return _int_env("SKILL_K8S_BIND_PORT", 9090)


def _runner_port() -> int:
    return _int_env("SKILL_K8S_RUNNER_PORT", 8888)


def _ttl_seconds() -> int:
    return _int_env("SKILL_K8S_TTL_SECONDS", 600)


# Past the skill's own exec HTTP wait (timeout + 15s) and a controller tick.
RUNNER_HOLD_BUFFER_SEC = 60


def runner_hold_seconds(timeout: int) -> int:
    """How long a skill run must keep the claim alive from now."""
    return max(_ttl_seconds(), int(timeout) + RUNNER_HOLD_BUFFER_SEC)


def _quota_gib() -> int:
    return _int_env("SKILL_K8S_QUOTA_GIB", 200)


def _artifacts_dir() -> Path:
    raw = _env("ARTIFACTS_DIR")
    if raw:
        return Path(raw)
    data = Path(_env("DATA_DIR") or "data")
    return data / "artifacts"


def _skills_dir() -> Path:
    raw = _env("SKILLS_DIR")
    if raw:
        return Path(raw)
    data = Path(_env("DATA_DIR") or "data")
    return data / "skills"


def in_cluster() -> bool:
    return (SA / "token").is_file()


def emulator_enabled() -> bool:
    """Local fake apiserver + bind + runtime. No cluster, no isolation."""
    return _env("SKILL_K8S_EMULATOR").lower() in ("1", "true", "yes")


def use_direct_http() -> bool:
    """Pod-network URLs. False on a laptop (or when SKILL_K8S_TUNNEL=1)."""
    if _env("SKILL_K8S_TUNNEL", "").lower() in ("1", "true", "yes"):
        return False
    if emulator_enabled():
        return True
    return in_cluster()


def claim_name(chat_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-." else "-" for c in chat_id)
    return f"runner-{safe}"[:63].strip("-.")


def _kubectl() -> list[str]:
    cmd = ["kubectl"]
    ctx = _env("SKILL_K8S_CONTEXT")
    if ctx:
        cmd.extend(["--context", ctx])
    return cmd


def _reap_children() -> None:
    for proc in list(_children):
        if proc.poll() is None:
            proc.kill()
    _children.clear()
    _forward_urls.clear()


atexit.register(_reap_children)


def _ensure_proxy() -> str:
    global _proxy_url
    if emulator_enabled():
        return (_env("SKILL_K8S_APISERVER") or "http://127.0.0.1:18080").rstrip("/")
    override = _env("SKILL_K8S_APISERVER")
    if override:
        return override.rstrip("/")
    with _lock:
        if _proxy_url:
            return _proxy_url
        proc = subprocess.Popen(
            [*_kubectl(), "proxy", "--port=0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _children.append(proc)
        deadline = time.time() + 20
        while time.time() < deadline:
            if proc.stdout is None:
                break
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    raise RuntimeError(f"kubectl proxy exited {proc.returncode}")
                continue
            match = re.search(r"127\.0\.0\.1:(\d+)", line)
            if match:
                _proxy_url = f"http://127.0.0.1:{match.group(1)}"
                return _proxy_url
        raise RuntimeError("kubectl proxy did not start")


def _port_forward(pod: str, remote_port: int) -> str:
    key = (pod, remote_port)
    with _lock:
        cached = _forward_urls.get(key)
        if cached:
            return cached
        proc = subprocess.Popen(
            [
                *_kubectl(),
                "-n",
                _ns(),
                "port-forward",
                f"pod/{pod}",
                f":{remote_port}",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _children.append(proc)
        deadline = time.time() + 20
        while time.time() < deadline:
            if proc.stdout is None:
                break
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    raise RuntimeError(
                        f"kubectl port-forward {pod}:{remote_port} exited {proc.returncode}"
                    )
                continue
            match = re.search(r"Forwarding from 127\.0\.0\.1:(\d+)", line)
            if match:
                url = f"http://127.0.0.1:{match.group(1)}"
                _forward_urls[key] = url
                return url
        raise RuntimeError(f"kubectl port-forward {pod}:{remote_port} did not start")


def _api_root() -> tuple[str, ssl.SSLContext | bool, dict[str, str]]:
    if in_cluster():
        host = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        port = os.getenv("KUBERNETES_SERVICE_PORT", "443")
        token = (SA / "token").read_text().strip()
        ctx = ssl.create_default_context(cafile=str(SA / "ca.crt"))
        return (
            f"https://{host}:{port}",
            ctx,
            {"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
    return (
        _ensure_proxy(),
        False,
        {"Content-Type": "application/json"},
    )


def _http_failure(method: str, url: str, timeout: int, exc: BaseException) -> RuntimeError:
    """aiohttp TimeoutError and ServerDisconnectedError have empty str()."""
    if isinstance(exc, TimeoutError):
        return RuntimeError(f"{method} {url} timed out after {timeout}s")
    detail = str(exc).strip() or type(exc).__name__
    return RuntimeError(f"{method} {url} failed: {detail}")


async def _k8s(
    method: str, path: str, body: Optional[dict] = None, timeout: int = 30
) -> dict:
    base, ctx, headers = _api_root()
    url = f"{base}{path}"
    if method.upper() == "PATCH":
        headers = {**headers, "Content-Type": "application/merge-patch+json"}
    connector = aiohttp.TCPConnector(ssl=ctx)
    try:
        async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
            async with session.request(
                method,
                url,
                json=body,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                raw = await resp.read()
                if resp.status >= 400:
                    raise RuntimeError(f"k8s {method} {path} -> {resp.status}: {raw[:400]!r}")
                return json.loads(raw) if raw else {}
    except (TimeoutError, aiohttp.ClientError) as exc:
        raise _http_failure(method, url, timeout, exc) from exc





def _crd(kind_plural: str, name: Optional[str] = None) -> str:
    root = (
        f"/apis/{_api_group()}/{_api_version()}"
        f"/namespaces/{_ns()}/{kind_plural}"
    )
    return f"{root}/{quote(name)}" if name else root


async def get_claim(chat_id: str) -> Optional[dict]:
    try:
        return await _k8s("GET", _crd("sandboxclaims", claim_name(chat_id)))
    except RuntimeError as exc:
        if "404" in str(exc):
            return None
        raise


async def create_claim(chat_id: str) -> dict:
    shutdown = datetime.now(timezone.utc) + timedelta(seconds=_ttl_seconds())
    body = {
        "apiVersion": f"{_api_group()}/{_api_version()}",
        "kind": "SandboxClaim",
        "metadata": {
            "name": claim_name(chat_id),
            "namespace": _ns(),
            "labels": {"weather-skills-chat": chat_id},
            "finalizers": [FINALIZER],
        },
            "spec": {
            "warmPoolRef": {"name": _pool()},
            "lifecycle": {
                "shutdownTime": shutdown.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "shutdownPolicy": "Delete",
            },
        },
    }
    return await _k8s("POST", _crd("sandboxclaims"), body)


async def extend_claim_ttl(claim: dict, seconds: Optional[int] = None) -> dict:
    name = claim["metadata"]["name"]
    hold = _ttl_seconds() if seconds is None else max(1, int(seconds))
    shutdown = datetime.now(timezone.utc) + timedelta(seconds=hold)
    claim = dict(claim)
    spec = dict(claim.get("spec") or {})
    lifecycle = dict(spec.get("lifecycle") or {})
    lifecycle["shutdownTime"] = shutdown.strftime("%Y-%m-%dT%H:%M:%SZ")
    lifecycle["shutdownPolicy"] = "Delete"
    spec["lifecycle"] = lifecycle
    spec.pop("shutdownTime", None)
    claim["spec"] = spec
    return await _k8s("PUT", _crd("sandboxclaims", name), claim)


async def hold_runner_for_skill(chat_id: str, timeout: int) -> None:
    """Bump claim shutdown so a cached runner cannot idle-stop mid-skill."""
    try:
        claim = await get_claim(chat_id)
        if not claim or claim.get("metadata", {}).get("deletionTimestamp"):
            return
        await extend_claim_ttl(claim, seconds=runner_hold_seconds(timeout))
    except Exception:
        log.debug("extend runner hold failed", exc_info=True)


async def delete_claim(chat_id: str, uid: Optional[str] = None) -> None:
    """Delete this chat's claim. With uid, only that claim: a later claim
    reuses the same name, and a stale delete must not remove it."""
    body = None
    if uid:
        body = {"apiVersion": "v1", "kind": "DeleteOptions", "preconditions": {"uid": uid}}
    try:
        await _k8s("DELETE", _crd("sandboxclaims", claim_name(chat_id)), body)
    except RuntimeError as exc:
        # 404: already gone. 409: the uid no longer matches, so it is gone too.
        if "404" in str(exc) or (uid and "409" in str(exc)):
            return
        raise


WAITING_STATUS = "Waiting on weather skills runner"
WAITING_ACTION = "weather_skills_runner"
# Worded so the model does not blame its own call: the runner failed, not the tool.
RUNNER_DIED_MESSAGE = (
    "Tool call failed: Sandbox runner died for unknown reasons "
    "(not clearly related to the tool call). Please try again."
)
RUNNER_OOM_MESSAGE = (
    "Tool call failed: the tool runner ran out of memory{detail}. "
    "Retry with less work at once, for example fewer skills in parallel or a "
    "smaller time range or region."
)
# Evicted for something other than memory (for example its node's disk).
RUNNER_EVICTED_MESSAGE = (
    "Tool call failed: Kubernetes evicted the tool runner{detail}. "
    "A new runner will be started. Please try again."
)
RUNNER_UNREACHABLE_MESSAGE = (
    "Sending request to tool runner failed, runner may be overloaded. "
    "Please try fewer tool calls at once or try again momentarily."
)
RUNNER_UNAVAILABLE_MESSAGE = "Failed to get a tool runner, please try again"
# Added to the system prompt when the tool runner is on. Models tend to read
# any runner failure as out of memory and cut their work down; only the OOM
# message above means that.
RUNNER_FAILURE_GUIDANCE = (
    "When a tool call fails because of the call itself, its result says so "
    "clearly: a skill error shows the skill's own output, a skill that ran past "
    'its timeout says it "did not finish within its timeout", and running out '
    'of memory always says "the tool runner ran out of memory". Do not assume a '
    "failure was caused by memory or by the size of the request unless the "
    "result says so. Other tool runner failures (the sandbox runner died, the "
    "runner may be overloaded, or no runner was available) are not caused by "
    "the call: first simply retry the same call, and only lower the amount of "
    "work if it fails again."
)
# Also added to the system prompt, with the limits read from the runner's
# SandboxTemplate (runner_resources_guidance), so it follows the infra chart.
RUNNER_RESOURCES_GUIDANCE = (
    "The tool runner has {cpus} and {memory} of memory, shared by all tool "
    "calls running at once. Please split and/or parallelize work as "
    "appropriate to fit within those limits."
)
RUNTIME_PROBE_TIMEOUT_SEC = 2
# A start that failed this recently is returned to new callers instead of
# starting again, so one tool-call turn waits through one start, not several.
RECENT_START_FAILURE_SEC = 15


class RunnerUnavailableError(RuntimeError):
    """No tool runner within the start time limit. The message is for the model."""

    def __init__(self) -> None:
        super().__init__(RUNNER_UNAVAILABLE_MESSAGE)


class _NotYet(Exception):
    """A start step is waiting on something (a claim being deleted, a pod)."""


def _start_timeout_seconds() -> int:
    return _int_env("SKILL_K8S_START_TIMEOUT_SECONDS", 180)


async def _until(deadline: float, what: str, step):
    """Run step() until it returns, backing off between failures, until deadline.

    Part of waiting for a runner, not a tool-call retry: callers see one
    RunnerUnavailableError when the start time limit runs out.
    """
    delay = 0.5
    while True:
        try:
            return await step()
        except RunnerUnavailableError:
            raise
        except Exception as exc:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                log.warning("tool runner start gave up at %s: %s", what, exc)
                raise RunnerUnavailableError() from exc
            pause = min(delay, remaining)
            if isinstance(exc, _NotYet):
                log.debug("tool runner start waiting at %s: %s", what, exc)
            else:
                log.info("tool runner start: %s failed, retrying in %.1fs: %s", what, pause, exc)
            await asyncio.sleep(pause)
            delay = min(delay * 2, 5.0)


def public_runner_state(state: Optional[str]) -> str:
    """Map internal runner_status to the top-bar / websocket state."""
    if state in ("ready", "starting", "degraded"):
        return state
    return "paused"


def _claim_ready(claim: dict) -> bool:
    for cond in (claim.get("status") or {}).get("conditions") or []:
        if cond.get("type") in ("Ready", "SandboxReady") and cond.get("status") == "True":
            return True
    return bool((claim.get("status") or {}).get("ready"))


def runner_needs_wait(claim: Optional[dict]) -> bool:
    """True when no runner pod is assigned yet (warm pool / first start / idle stop)."""
    return claim is None or not (_claim_ready(claim) and _pod_ref(claim))


async def _emit_waiting(emitter, done: bool) -> None:
    if not emitter:
        return
    data = {"action": WAITING_ACTION, "description": WAITING_STATUS, "done": done}
    if done:
        data["hidden"] = True
    await emitter({"type": "status", "data": data})


def _template_name() -> str:
    # The chart names the warm pool and its SandboxTemplate the same.
    return _env("SKILL_K8S_SANDBOX_TEMPLATE") or _pool()


_BINARY_SUFFIXES = {"Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40}
_DECIMAL_SUFFIXES = {"k": 10**3, "M": 10**6, "G": 10**9, "T": 10**12}


def _cpu_cores(quantity) -> Optional[float]:
    """A Kubernetes CPU quantity ("3", "2.5", "3000m") in cores."""
    raw = str(quantity or "").strip()
    try:
        if raw.endswith("m"):
            return float(raw[:-1]) / 1000
        return float(raw) if raw else None
    except ValueError:
        return None


def _memory_gib(quantity) -> Optional[float]:
    """A Kubernetes memory quantity ("8Gi", "3686Mi", "8G", bytes) in GiB."""
    raw = str(quantity or "").strip()
    try:
        for suffixes in (_BINARY_SUFFIXES, _DECIMAL_SUFFIXES):
            for suffix, scale in suffixes.items():
                if raw.endswith(suffix):
                    return float(raw[: -len(suffix)]) * scale / 2**30
        return float(raw) / 2**30 if raw else None
    except ValueError:
        return None


def _runner_limits(template: dict) -> Optional[tuple[float, float]]:
    """(CPU cores, memory GiB) limits of the runner container in a SandboxTemplate."""
    pod = ((template.get("spec") or {}).get("podTemplate") or {}).get("spec") or {}
    containers = pod.get("containers") or []
    runner = next((c for c in containers if c.get("name") == "runner"), None)
    if runner is None and containers:
        runner = containers[0]
    limits = ((runner or {}).get("resources") or {}).get("limits") or {}
    cpus, memory = _cpu_cores(limits.get("cpu")), _memory_gib(limits.get("memory"))
    if not cpus or not memory:
        return None
    return cpus, memory


def _amount(value: float) -> str:
    return str(int(value)) if value == int(value) else f"{value:.1f}"


# The prompt line is read once per this long; a failed read is retried sooner.
RUNNER_LIMITS_CACHE_SEC = 300
RUNNER_LIMITS_RETRY_SEC = 60
# Short: this runs before every model call while the tool runner is on.
RUNNER_LIMITS_TIMEOUT_SEC = 3
_runner_limits_cache: Optional[tuple[float, float, Optional[str]]] = None


async def runner_resources_guidance() -> Optional[str]:
    """The system-prompt line with the runner's CPU and memory limits.

    Read from the runner's SandboxTemplate, so it matches what the infra chart
    deploys in each environment. None (no line) when it cannot be read.
    """
    global _runner_limits_cache
    now = time.monotonic()
    if _runner_limits_cache is not None:
        read_at, ttl, text = _runner_limits_cache
        if now - read_at < ttl:
            return text
    text = None
    try:
        template = await _k8s(
            "GET", _crd("sandboxtemplates", _template_name()), timeout=RUNNER_LIMITS_TIMEOUT_SEC
        )
        limits = _runner_limits(template)
        if limits:
            cpus, memory = limits
            text = RUNNER_RESOURCES_GUIDANCE.format(
                cpus=f"{_amount(cpus)} CPU core{'' if cpus == 1 else 's'}",
                memory=f"{_amount(round(memory, 1))} GiB",
            )
        else:
            log.warning("runner template %s has no cpu/memory limits", _template_name())
    except Exception as exc:
        log.warning("runner limits unavailable template=%s: %s", _template_name(), exc)
    ttl = RUNNER_LIMITS_CACHE_SEC if text else RUNNER_LIMITS_RETRY_SEC
    _runner_limits_cache = (now, ttl, text)
    return text


def _pod_ref(claim: dict) -> Optional[str]:
    status = claim.get("status") or {}
    ref = status.get("sandbox") or status.get("sandboxRef") or status.get("podRef") or {}
    return ref.get("name") or status.get("podName")


async def get_pod(name: str) -> dict:
    return await _k8s("GET", f"/api/v1/namespaces/{_ns()}/pods/{quote(name)}")


async def _http_json(
    method: str,
    url: str,
    *,
    json_body: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = 30,
) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                url,
                json=json_body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                raw = await resp.read()
                if resp.status >= 400:
                    raise RuntimeError(f"{method} {url} -> {resp.status}: {raw[:300]!r}")
                if not raw:
                    return {}
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return {"raw": raw.decode("utf-8", errors="replace")}
    except (TimeoutError, aiohttp.ClientError) as exc:
        raise _http_failure(method, url, timeout, exc) from exc


async def bind_token() -> str:
    global _bind_token
    env = _env("SKILL_K8S_BIND_TOKEN")
    if env:
        return env
    if _bind_token:
        return _bind_token
    data = await _k8s("GET", f"/api/v1/namespaces/{_ns()}/secrets")
    for secret in data.get("items") or []:
        payload = secret.get("data") or {}
        if payload.get("token") and payload.get("metaurl"):
            _bind_token = base64.b64decode(payload["token"]).decode()
            return _bind_token
    raise RuntimeError("SKILL_K8S_BIND_TOKEN is empty and no daemon secret was found")


async def _daemon_on_host(host_ip: str) -> str:
    selector = quote(DAEMON_LABEL)
    data = await _k8s(
        "GET", f"/api/v1/namespaces/{_ns()}/pods?labelSelector={selector}"
    )
    for pod in data.get("items") or []:
        if (pod.get("status") or {}).get("hostIP") == host_ip:
            return pod["metadata"]["name"]
        if (pod.get("status") or {}).get("podIP") == host_ip:
            return pod["metadata"]["name"]
    raise RuntimeError(f"no bind daemon on host {host_ip}")


async def _pod_name_for_ip(pod_ip: str) -> str:
    data = await _k8s("GET", f"/api/v1/namespaces/{_ns()}/pods")
    for pod in data.get("items") or []:
        if (pod.get("status") or {}).get("podIP") == pod_ip:
            return pod["metadata"]["name"]
    raise RuntimeError(f"no pod with IP {pod_ip}")


async def _bind_base(pod: dict) -> str:
    host_ip = (pod.get("status") or {}).get("hostIP")
    if not host_ip:
        raise RuntimeError("tool runner pod has no hostIP")
    if use_direct_http():
        return f"http://{host_ip}:{_bind_port()}"
    return _port_forward(await _daemon_on_host(host_ip), _bind_port())


def _pod_runner_port(pod: Optional[dict] = None) -> int:
    if pod:
        for container in (pod.get("spec") or {}).get("containers") or []:
            for port in container.get("ports") or []:
                if port.get("name") == "runtime":
                    return int(port.get("hostPort") or port.get("containerPort") or _runner_port())
    return _runner_port()


# Baked into the runner image (rhiza-research/infrastructure images/sandbox-runner). /workspace is an
# emptyDir, so a cache under it would hide the prewarmed wheels.
RUNNER_UV_CACHE_DIR = "/opt/uv-cache"


def _runner_workspace(chat_id: str) -> str:
    # JuiceFS late-bind dest. /workspace is the runner emptyDir.
    return _env("SKILL_K8S_RUNNER_WORKSPACE", "/workspace/chat").rstrip("/") or "/workspace/chat"


def _uv_cache_dir(workspace: str) -> str:
    return _env("SKILL_K8S_UV_CACHE_DIR", RUNNER_UV_CACHE_DIR) or RUNNER_UV_CACHE_DIR


def _runner_packs_root() -> str:
    return str(Path(_runner_workspace("")).parent / ".skill-packs")


async def _runner_base(
    pod_ip: str, pod_name: Optional[str] = None, pod: Optional[dict] = None
) -> str:
    port = _pod_runner_port(pod)
    if use_direct_http():
        return f"http://{pod_ip}:{port}"
    name = pod_name or await _pod_name_for_ip(pod_ip)
    return _port_forward(name, port)


async def own_workspace(
    chat_id: str,
    pod: dict,
    paths: Optional[list[str]] = None,
    trees: Optional[list[str]] = None,
) -> None:
    """Ask the bind daemon to chown/chmod specific files (`paths`) or walked trees."""
    if not paths and not trees:
        return
    base = await _bind_base(pod)
    headers = {"Authorization": f"Bearer {await bind_token()}"}
    await _http_json(
        "POST",
        f"{base}/own",
        json_body={
            "chat_id": chat_id,
            "paths": list(paths or []),
            "trees": list(trees or []),
        },
        headers=headers,
    )


async def bind_workspace(chat_id: str, pod: dict) -> None:
    uid = (pod.get("metadata") or {}).get("uid")
    if not uid:
        raise RuntimeError("tool runner pod has no uid")
    base = await _bind_base(pod)
    headers = {"Authorization": f"Bearer {await bind_token()}"}
    await _http_json(
        "POST",
        f"{base}/quota",
        json_body={"chat_id": chat_id, "capacity_gib": _quota_gib()},
        headers=headers,
    )
    await own_workspace(chat_id, pod, paths=["intermediate_results"])
    await _http_json(
        "POST",
        f"{base}/bind",
        json_body={"chat_id": chat_id, "pod_uid": uid},
        headers=headers,
    )


async def verify_runtime(
    pod_ip: str, pod_name: Optional[str] = None, pod: Optional[dict] = None
) -> dict:
    base = await _runner_base(pod_ip, pod_name, pod)
    return await _http_json("GET", f"{base}/health")


def _pack_root(skill_dir: Path) -> Path:
    pack_root = Path(skill_dir).resolve()
    skills_root = _skills_dir().resolve()
    try:
        pack_root.relative_to(skills_root)
        while pack_root.parent != skills_root and pack_root != skills_root:
            pack_root = pack_root.parent
    except ValueError:
        pack_root = Path(skill_dir).resolve()
    return pack_root


def remote_script_path(skill_dir: Path, script_path: Path) -> str:
    pack = _pack_root(skill_dir)
    root = _runner_packs_root()
    try:
        rel = Path(skill_dir).resolve().relative_to(pack)
        mid = "" if str(rel) in (".", "") else f"/{rel.as_posix()}"
        return f"{root}/{pack.name}{mid}/scripts/{script_path.name}"
    except Exception:
        return f"{root}/{Path(skill_dir).name}/scripts/{script_path.name}"


_SKIP_PACK_PARTS = {"__pycache__", ".git", ".venv", ".uv-cache", ".mypy_cache"}


def _tar_pack(pack_root: Path) -> bytes:
    buf = io.BytesIO()

    def skip(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if any(part in _SKIP_PACK_PARTS for part in Path(info.name).parts):
            return None
        return info

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(pack_root, arcname=pack_root.name, filter=skip)
    return buf.getvalue()


PACKS_ANN = "weather-skills.io/packs"
BOUND_ANN = "weather-skills.io/bound"
SAFE_TO_EVICT_ANN = "cluster-autoscaler.kubernetes.io/safe-to-evict"


def _cached_runner(chat_id: str) -> Optional[dict]:
    """Return the last good runner for this chat.

    Kept for the claim idle lifetime and refreshed on use, so an open chat
    does not re-list packs or re-bind. Dropped when the runner fails or the
    idle timer runs out with no use.
    """
    hit = _ready_cache.get(chat_id)
    if not hit:
        return None
    stamp, info = hit
    if time.monotonic() - stamp > float(_ttl_seconds()):
        _ready_cache.pop(chat_id, None)
        return None
    _ready_cache[chat_id] = (time.monotonic(), info)
    return info


def _store_runner(chat_id: str, info: dict) -> None:
    _ready_cache[chat_id] = (time.monotonic(), info)


def _drop_runner(chat_id: str) -> None:
    _ready_cache.pop(chat_id, None)
    task = _starts.get(chat_id)
    if task is not None and task.done():
        _starts.pop(chat_id, None)


HEALTH_OK = "ok"
HEALTH_UNHEALTHY = "unhealthy"
HEALTH_NO_ANSWER = "no_answer"


async def _runner_health(info: Optional[dict]) -> str:
    """The runner's own /health answer, within RUNTIME_PROBE_TIMEOUT_SEC.

    HEALTH_UNHEALTHY means it answered with an error status (503 when its chat
    storage is disconnected). HEALTH_NO_ANSWER (timeout, connection error) is
    not a verdict: a runner busy with many skills can be slow to answer.
    """
    if not info or not info.get("pod_ip"):
        return HEALTH_NO_ANSWER
    try:
        base = await _runner_base(info["pod_ip"], info.get("pod_name"), info.get("pod"))
        await _http_json("GET", f"{base}/health", timeout=RUNTIME_PROBE_TIMEOUT_SEC)
        return HEALTH_OK
    except RuntimeError as exc:
        # _http_json reports an HTTP error status as "<METHOD> <url> -> <status>: ...".
        return HEALTH_UNHEALTHY if " -> " in str(exc) else HEALTH_NO_ANSWER
    except Exception:
        return HEALTH_NO_ANSWER


def _pod_ready(pod: dict) -> bool:
    """Kubernetes' view: Running, no terminated container, and Ready."""
    if _pod_dead(pod) or (pod.get("status") or {}).get("phase") != "Running":
        return False
    for cond in (pod.get("status") or {}).get("conditions") or []:
        if cond.get("type") == "Ready":
            return cond.get("status") == "True"
    return True  # no conditions reported (the laptop emulator)


async def _pod_alive(pod_name: Optional[str]) -> bool:
    if not pod_name:
        return False
    try:
        pod = await get_pod(pod_name)
    except Exception as exc:
        # Gone means dead; any other API error is not a verdict on the runner.
        return "404" not in str(exc)
    return _pod_ready(pod)


def _pod_moved(info: Optional[dict], pod: Optional[dict]) -> bool:
    """The pod is no longer at the address chat sends this runner's calls to.

    Under gVisor a container restart (an OOM kill) starts a new sandbox with a
    new pod IP, and the old IP can later go to another runner.
    """
    if not info or not pod:
        return False
    meta, status = pod.get("metadata") or {}, pod.get("status") or {}
    known_uid = ((info.get("pod") or {}).get("metadata") or {}).get("uid")
    if known_uid and meta.get("uid") and meta["uid"] != known_uid:
        return True
    pod_ip, known_ip = status.get("podIP"), info.get("pod_ip")
    return bool(pod_ip and known_ip and pod_ip != known_ip)


async def _runner_alive(info: Optional[dict]) -> bool:
    """Keep using this runner?

    Only the runner answering /health with an error, Kubernetes saying its
    pod is gone or not Ready, or the pod having moved to another address
    condemns it. A slow or missing /health answer falls back to Kubernetes'
    readiness, so a busy runner is kept.
    """
    health = await _runner_health(info)
    if health == HEALTH_UNHEALTHY:
        return False
    pod_name = (info or {}).get("pod_name")
    if not pod_name:
        return health == HEALTH_OK
    try:
        pod = await get_pod(pod_name)
    except Exception as exc:
        # Gone means dead; any other API error is not a verdict on the runner.
        return "404" not in str(exc)
    if pod is None:
        return health == HEALTH_OK
    if _pod_moved(info, pod):
        return False
    return health == HEALTH_OK or _pod_ready(pod)


async def _claim_runner_alive(claim: dict) -> bool:
    """True if this claim is still starting, or its runner is alive.

    The pod is checked before the claim's readiness: Agent Sandbox marks a
    claim not ready when its pod is evicted, but never replaces that pod, so
    "not ready" alone would wait on a dead runner until the claim's TTL.
    """
    pod_name = _pod_ref(claim)
    if not pod_name:
        return True  # no runner assigned yet
    try:
        pod = await get_pod(pod_name)
    except Exception as exc:
        if "404" in str(exc):
            # A starting claim can name its pod before the pod exists.
            return not _claim_ready(claim)
        return True  # an API error is not a verdict
    if _pod_gone_for_good(pod):
        return False
    if not _claim_ready(claim):
        return True
    pod_ip = (pod.get("status") or {}).get("podIP")
    if not pod_ip:
        return _pod_ready(pod)
    return await _runner_alive({"pod_ip": pod_ip, "pod_name": pod_name, "pod": pod})


async def _adopt_or_replace_claim(chat_id: str) -> dict:
    """One step of getting a claim: keep a live one, or clear the way for a new one.

    Raises _NotYet while an old claim is still being deleted (its finalizer
    unbinds storage first), and after deleting a dead one; _until repeats the
    step, and a later pass creates the new claim under the same name.
    """
    claim = await get_claim(chat_id)
    if claim is None:
        return await create_claim(chat_id)
    meta = claim.get("metadata") or {}
    if meta.get("deletionTimestamp"):
        raise _NotYet("previous tool runner is still shutting down")
    if await _claim_runner_alive(claim):
        if not _claim_ready(claim):
            # Still starting: its TTL was set at create. Extending a claim
            # that is not ready would keep a stuck one alive on every retry.
            return claim
        try:
            return await extend_claim_ttl(claim)
        except Exception:
            log.debug("extend ttl failed", exc_info=True)
            return claim
    log.info("replacing dead runner claim chat=%s", chat_id)
    await delete_claim(chat_id, uid=meta.get("uid"))
    raise _NotYet("deleted the dead runner's claim")


def _pack_names(paths: list[Path]) -> set[str]:
    return {path.name for path in paths}


def _missing_packs(have: set[str], packs: list[Path]) -> list[Path]:
    return [path for path in packs if path.name not in have]


def _tool_skill_dir(tool) -> str:
    meta = getattr(tool, "meta", None)
    if meta is None:
        return ""
    manifest = getattr(meta, "manifest", None)
    if manifest is None and isinstance(meta, dict):
        manifest = meta.get("manifest")
    if not isinstance(manifest, dict):
        return ""
    raw = manifest.get("skill_dir")
    return str(raw) if raw else ""


def _latest_skill_packs(records: list[dict], catalog: list) -> list[Path]:
    """Pack directory for each active skill, keeping only its newest version."""
    from open_webui.utils.skill_version import prefer_incoming_tool_version

    best: dict[str, dict] = {}
    for record in records:
        if record.get("enabled") is False:
            continue
        name = record.get("skill_name")
        if not name:
            continue
        current = best.get(name)
        if current is None or prefer_incoming_tool_version(
            record.get("version"), current.get("version")
        ):
            best[name] = record
    by_id = {tool.id: tool for tool in catalog}
    packs: dict[str, Path] = {}
    for record in best.values():
        tool = by_id.get(record["id"])
        if tool is None:
            continue
        raw = _tool_skill_dir(tool)
        if not raw:
            continue
        pack = _pack_root(Path(raw))
        if pack.is_dir():
            packs[pack.name] = pack
    return [packs[name] for name in sorted(packs)]


def _packs_for_chat(chat_id: str) -> list[Path]:
    """Pack checkouts to put on this chat's runner.

    One directory per skill name: the copy the chat can use, at the newest
    version. Other checkouts of the same skill stay on the chat server.
    """
    from open_webui.models.chats import Chats
    from open_webui.models.tools import Tools
    from open_webui.models.users import Users
    from open_webui.utils.tools import accessible_skill_records

    chat = Chats.get_chat_by_id(chat_id)
    if chat is None or not chat.user_id:
        log.warning("skill packs skipped, chat missing id=%s", chat_id)
        return []
    user = Users.get_user_by_id(chat.user_id)
    if user is None:
        log.warning("skill packs skipped, user missing chat=%s", chat_id)
        return []
    catalog = Tools.get_tool_catalog()
    records = accessible_skill_records(
        user, organization_id=chat.organization_id, catalog=catalog
    )
    packs = _latest_skill_packs(records, catalog)
    log.info(
        "skill packs for chat=%s skills=%s packs=%s",
        chat_id,
        len({r.get("skill_name") for r in records if r.get("skill_name")}),
        [path.name for path in packs],
    )
    return packs


async def _annotate_pod(pod: dict, updates: dict) -> None:
    name = (pod.get("metadata") or {}).get("name")
    if not name:
        return
    try:
        await _k8s(
            "PATCH",
            f"/api/v1/namespaces/{_ns()}/pods/{quote(name)}",
            {"metadata": {"annotations": updates}},
        )
        pod.setdefault("metadata", {}).setdefault("annotations", {}).update(updates)
    except Exception:
        log.warning("annotate pod failed name=%s keys=%s", name, list(updates), exc_info=True)


def _runner_log_name(info: Optional[dict]) -> str:
    """Pod name for chat-side skill logs. Falls back to pod IP."""
    if not info:
        return "?"
    return info.get("pod_name") or info.get("pod_ip") or "?"


def _runner_info(pod: dict, pod_name: Optional[str] = None) -> dict:
    name = pod_name or (pod.get("metadata") or {}).get("name")
    return {
        "pod": pod,
        "pod_name": name,
        "pod_ip": (pod.get("status") or {}).get("podIP"),
    }


async def _listed_packs(info: dict) -> Optional[set[str]]:
    base = await _runner_base(info["pod_ip"], info.get("pod_name"), info.get("pod"))
    try:
        body = await _http_json("GET", f"{base}/packs")
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise
        listing = await _http_json(
            "POST",
            f"{base}/exec",
            json_body={
                "cmd": ["ls", "-1", _runner_packs_root()],
                "cwd": "/",
                "timeout": 10,
            },
            timeout=15,
        )
        if int(listing.get("exit_code", 1)) != 0:
            return set()
        return {
            line.strip()
            for line in (listing.get("stdout") or "").splitlines()
            if line.strip() and not line.strip().startswith(".")
        }
    return {str(name) for name in (body.get("packs") or []) if name}


async def _packs_ready_on_runner(
    pod: dict, chat_id: str, info: Optional[dict] = None
) -> bool:
    anns = (pod.get("metadata") or {}).get("annotations") or {}
    if anns.get(PACKS_ANN) == "ready":
        return True
    if info is None:
        info = _runner_info(pod)
    if not info.get("pod_ip"):
        return False
    have = await _listed_packs(info) or set()
    return _pack_names(_packs_for_chat(chat_id)).issubset(have)


async def _ensure_pack_on_runner(info: dict, skill_dir: Path) -> str:
    """Put the pack on the runner emptyDir. JuiceFS copytree of many files is slow."""
    pack = _pack_root(skill_dir)
    dest = f"{_runner_packs_root()}/{pack.name}"
    base = await _runner_base(info["pod_ip"], info.get("pod_name"), info.get("pod"))
    started = time.monotonic()
    archive = base64.b64encode(_tar_pack(pack)).decode()
    packed = time.monotonic()
    result = await _http_json(
        "POST",
        f"{base}/unpack",
        json_body={"dest": dest, "archive": archive},
        timeout=180,
    )
    log.info(
        "skill pack pushed dest=%s pack=%.2fs upload=%.2fs skipped=%s",
        dest,
        packed - started,
        time.monotonic() - packed,
        bool(result.get("skipped")),
    )
    if result.get("ok") is False:
        raise RuntimeError(result.get("error") or "unpack failed")
    return dest


async def _ensure_packs_on_runner(info: dict, chat_id: str) -> None:
    wanted = _packs_for_chat(chat_id)
    have = await _listed_packs(info) or set()
    missing = _missing_packs(have, wanted)
    if not missing:
        log.info("skill packs already on runner n=%s", len(have))
        return
    started = time.monotonic()
    await asyncio.gather(*[_ensure_pack_on_runner(info, pack) for pack in missing])
    log.info(
        "skill packs ready n=%s missing=%s elapsed=%.2fs",
        len(wanted),
        len(missing),
        time.monotonic() - started,
    )


def _k8s_runner_path_on() -> bool:
    backend = _env("SKILL_SANDBOX_BACKEND", "landlock").lower()
    enabled = _env("SKILL_K8S_SANDBOX_ENABLED").lower() in ("1", "true", "yes")
    return backend == "k8s" and enabled


def _start_in_flight(chat_id: str) -> bool:
    task = _starts.get(chat_id)
    return task is not None and not task.done()


def start_runner(chat_id: str) -> asyncio.Task:
    """Kick the one start for this chat. Does not wait. Safe to call again.

    Reuses an in-flight start, or a start that finished while this chat's
    runner is still remembered as ready. After idle stop the cache expires
    and the next call starts again.
    """
    with _lock:
        task = _starts.get(chat_id)
        if task is not None and not task.done():
            return task
        if (
            task is not None
            and not task.cancelled()
            and task.exception() is None
            and _cached_runner(chat_id) is not None
        ):
            return task
        if (
            task is not None
            and not task.cancelled()
            and task.exception() is not None
            and time.monotonic() - _start_failed_at.get(chat_id, 0.0) < RECENT_START_FAILURE_SEC
        ):
            return task
        task = asyncio.create_task(_run_start(chat_id), name=f"runner-start-{chat_id}")
        _starts[chat_id] = task
        return task


_start_failed_at: dict[str, float] = {}


async def _run_start(chat_id: str) -> dict:
    """Get this chat's runner ready: claimed, bound, and its skill packs unpacked.

    The runner counts as ready only after all three. Each step backs off and
    tries again until one time limit for the whole start; past it the caller
    gets RunnerUnavailableError.
    """
    cached = _cached_runner(chat_id)
    if cached and await _runner_alive(cached):
        return cached
    if cached:
        _drop_runner(chat_id)
    deadline = time.monotonic() + _start_timeout_seconds()
    try:

        async def claimed() -> dict:
            # Every pass re-checks the claim, so a runner that dies while
            # this start waits (evicted, OOM) is replaced, not waited on.
            claim = await _adopt_or_replace_claim(chat_id)
            if _claim_ready(claim) and _pod_ref(claim):
                return claim
            raise _NotYet("tool runner is not ready yet")

        claim = await _until(deadline, "ready claim", claimed)
        pod_name = _pod_ref(claim)

        async def bind() -> dict:
            pod = await get_pod(pod_name)
            annotations = (pod.get("metadata") or {}).get("annotations") or {}
            if annotations.get(BOUND_ANN) != chat_id:
                await bind_workspace(chat_id, pod)
                await _annotate_pod(pod, {BOUND_ANN: chat_id, SAFE_TO_EVICT_ANN: "false"})
            elif annotations.get(SAFE_TO_EVICT_ANN) != "false":
                await _annotate_pod(pod, {SAFE_TO_EVICT_ANN: "false"})
            if not (pod.get("status") or {}).get("podIP"):
                raise _NotYet("tool runner has no pod IP yet")
            return pod

        pod = await _until(deadline, "bind", bind)
        pod_ip = pod["status"]["podIP"]
        await _until(deadline, "runtime", lambda: verify_runtime(pod_ip, pod_name, pod))
        info = {"claim": claim, "pod": pod, "pod_ip": pod_ip, "pod_name": pod_name}

        async def packs() -> None:
            if not await _packs_ready_on_runner(pod, chat_id, info):
                await _ensure_packs_on_runner(info, chat_id)
                await _annotate_pod(pod, {PACKS_ANN: "ready"})

        await _until(deadline, "skill packs", packs)
        _store_runner(chat_id, info)
        _start_failed_at.pop(chat_id, None)
        return info
    except Exception:
        _start_failed_at[chat_id] = time.monotonic()
        _drop_runner(chat_id)
        raise


def runner_ready(chat_id: Optional[str]) -> bool:
    """True when a skill can run without waiting. Cache only — no k8s /packs probe."""
    if not chat_id or chat_id == "local":
        return True
    if not _k8s_runner_path_on():
        return True
    return _cached_runner(str(chat_id)) is not None


async def emit_runner_waiting(emitter, done: bool) -> None:
    await _emit_waiting(emitter, done)


async def await_runner_for_chat(chat_id: Optional[str], emitter=None) -> None:
    """Wait until this chat's runner is ready enough to run a skill.

    Does not probe the runner. That probe (claim + packs) was delaying every
    tool card, including when the runner was already up. Leaves the waiting
    line up so the caller can paint tool cards first, then hide it.
    """
    if runner_ready(chat_id):
        return
    chat_id = str(chat_id)
    task = start_runner(chat_id)
    await _emit_waiting(emitter, False)
    # The start has its own time limit; this only guards against a hang.
    await asyncio.wait_for(asyncio.shield(task), timeout=_start_timeout_seconds() + 30)


async def ensure_runner(chat_id: str, *, emitter=None) -> dict:
    """Return a ready runner, starting one if needed.

    A remembered runner that no longer answers /health (dead, or its storage
    is disconnected) is replaced here, with the waiting status shown, so the
    tool call runs on the new runner instead of failing.
    """
    cached = _cached_runner(chat_id)
    if cached and await _runner_alive(cached):
        return cached
    if cached:
        _drop_runner(chat_id)
    task = start_runner(chat_id)
    if emitter is None:
        return await asyncio.shield(task)
    await _emit_waiting(emitter, False)
    try:
        return await asyncio.shield(task)
    finally:
        await _emit_waiting(emitter, True)


# A Ready runner that has not answered /health for this long reads degraded
# (stuck, or very busy). Display only: nothing is deleted for it.
DEGRADED_AFTER_NO_ANSWER_SEC = 30.0
_no_answer_since: dict[str, float] = {}


def _ready_or_degraded(chat_id: str, health: str) -> str:
    if health == HEALTH_OK:
        _no_answer_since.pop(chat_id, None)
        return "ready"
    since = _no_answer_since.setdefault(chat_id, time.monotonic())
    return "degraded" if time.monotonic() - since >= DEGRADED_AFTER_NO_ANSWER_SEC else "ready"


async def _pod_or_none(name: Optional[str]) -> Optional[dict]:
    if not name:
        return None
    try:
        return await get_pod(name)
    except Exception:
        return None


async def runner_status(chat_id: str) -> dict:
    """Read the runner's state for the top bar. Read only: starts and deletes nothing.

    ready: answering /health (or Ready and only briefly silent).
    degraded: answers /health with an error (503), its bound pod is NotReady,
      or Ready but silent for DEGRADED_AFTER_NO_ANSWER_SEC; or its pod was
      evicted or is being deleted, until its claim is released.
    starting: a start is in flight, or a claimed runner is not bound yet.
    absent (paused): no claim, or the claim is being deleted.

    A ready result is remembered so later status and tool calls do not list
    packs again. Packs are listed only when the pod is not already marked ready.
    """
    name = claim_name(chat_id)
    cached = _cached_runner(chat_id)
    if cached:
        health = await _runner_health(cached)
        if health == HEALTH_OK:
            _no_answer_since.pop(chat_id, None)
            return {"state": "ready", "claim": name}
        if health == HEALTH_UNHEALTHY:
            # Replacing it is the in-flight watcher's or the next tool call's job.
            _drop_runner(chat_id)
            return {"state": "degraded", "claim": name}
        pod = await _pod_or_none(cached.get("pod_name"))
        if pod is not None and _pod_ready(pod) and not _pod_moved(cached, pod):
            return {"state": _ready_or_degraded(chat_id, health), "claim": name}
        # Not ready, gone, or restarted at a new address: read it afresh below.
        _drop_runner(chat_id)
    if _start_in_flight(chat_id):
        return {"state": "starting", "claim": name}
    claim = await get_claim(chat_id)
    if not claim or claim.get("metadata", {}).get("deletionTimestamp"):
        _no_answer_since.pop(chat_id, None)
        return {"state": "absent"}
    pod = await _pod_or_none(_pod_ref(claim))
    if pod is not None and _pod_gone_for_good(pod):
        # Evicted or being deleted, bound or not: it will not come back, so
        # it is not starting. Paused once its claim is released.
        return {"state": "degraded", "claim": name}
    annotations = ((pod or {}).get("metadata") or {}).get("annotations") or {}
    bound = pod is not None and annotations.get(BOUND_ANN) == chat_id
    if bound and not _pod_ready(pod):
        # Agent Sandbox marks the claim not ready along with its pod, so check
        # the pod first: a bound runner that is not ready is broken. An unbound
        # one falls through and reads starting below.
        return {"state": "degraded", "claim": name}
    if not _claim_ready(claim):
        return {"state": "starting", "claim": name}
    if pod is None:
        return {"state": "absent"}
    pod_ip = (pod.get("status") or {}).get("podIP")
    info = {
        "claim": claim,
        "pod": pod,
        "pod_ip": pod_ip,
        "pod_name": _pod_ref(claim),
    }
    health = await _runner_health(info)
    if health == HEALTH_UNHEALTHY:
        return {"state": "degraded", "claim": name}
    if health == HEALTH_NO_ANSWER:
        if bound:
            return {"state": _ready_or_degraded(chat_id, health), "claim": name}
        return {"state": "starting", "claim": name}
    _no_answer_since.pop(chat_id, None)
    try:
        if await _packs_ready_on_runner(pod, chat_id):
            if pod_ip:
                _store_runner(chat_id, info)
            return {"state": "ready", "claim": name}
    except Exception:
        log.debug("runner pack listing failed", exc_info=True)
    return {"state": "starting", "claim": name}


async def runner_metrics(chat_id: str) -> dict:
    try:
        claim = await get_claim(chat_id)
        if not claim or not _claim_ready(claim):
            raise RuntimeError("tool runner is not ready")
        pod_name = _pod_ref(claim)
        pod = await get_pod(pod_name)
        uid = (pod.get("metadata") or {}).get("uid")
        if not uid:
            raise RuntimeError("tool runner pod has no uid")
        base = await _bind_base(pod)
        headers = {"Authorization": f"Bearer {await bind_token()}"}
        return await _http_json(
            "GET",
            f"{base}/metrics?pod_uid={quote(uid)}",
            headers=headers,
        )
    except Exception:
        _drop_runner(chat_id)
        raise


def _pod_dead(pod: dict) -> bool:
    if (pod.get("metadata") or {}).get("deletionTimestamp"):
        return True
    status = pod.get("status") or {}
    if status.get("phase") in ("Failed", "Succeeded"):
        return True
    return any(
        "terminated" in (container.get("state") or {})
        for container in status.get("containerStatuses") or []
    )


def _pod_gone_for_good(pod: dict) -> bool:
    """Evicted, completed, or being deleted: this runner will not come back.

    Agent Sandbox never replaces such a pod. Narrower than _pod_dead: a
    container that is terminated only until the kubelet restarts it (after an
    OOM kill) does not count.
    """
    if (pod.get("metadata") or {}).get("deletionTimestamp"):
        return True
    return (pod.get("status") or {}).get("phase") in ("Failed", "Succeeded")


def _eviction_detail(message: str) -> str:
    return f" (evicted: {message.strip()[:200]})"


def _oom_detail(pod: dict) -> Optional[str]:
    """' (<detail>)' when the runner pod ran out of memory, else None."""
    status = pod.get("status") or {}
    if status.get("reason") == "Evicted":
        message = status.get("message") or ""
        if "memory" in message.lower():
            return _eviction_detail(message)
    for container in status.get("containerStatuses") or []:
        for key in ("state", "lastState"):
            terminated = (container.get(key) or {}).get("terminated") or {}
            if terminated.get("reason") == "OOMKilled":
                return " (OOMKilled)"
    return None


async def _eviction_event(pod: dict) -> Optional[str]:
    """The message of this pod's Evicted event, if the kubelet has evicted it.

    The kubelet records the event when it decides to evict, before it kills
    the runner. The pod itself reads Evicted only after the kill, which under
    gVisor can take more than ten seconds.
    """
    uid = (pod.get("metadata") or {}).get("uid")
    if not uid:
        return None
    selector = quote(f"involvedObject.uid={uid},reason=Evicted", safe="=,")
    try:
        events = await _k8s("GET", f"/api/v1/namespaces/{_ns()}/events?fieldSelector={selector}")
    except Exception:
        log.debug("eviction event lookup failed pod=%s", uid, exc_info=True)
        return None
    for event in events.get("items") or []:
        message = event.get("message") or event.get("note") or ""
        if message:
            return message
    return None


# How long a tool call whose runner stopped answering waits for Kubernetes to
# say why (OOM kill, eviction) before telling the model it may be overloaded.
LOST_RUNNER_VERDICT_SEC = 15.0
LOST_RUNNER_POLL_SEC = 1.0


def _lost_runner_verdict_seconds() -> float:
    return LOST_RUNNER_VERDICT_SEC


async def _lost_exec_message(chat_id: str, info: dict, runner_died: bool = False) -> str:
    """What the model is told when the request to the runner failed.

    runner_died: the in-flight watcher saw the runner restart, move or go
    away, so it is not waited on as possibly overloaded.

    Out of memory (OOM kill, or a memory eviction) says so; a pod that is
    gone, terminated, or being deleted died; a runner answering /health with
    an error is replaced. Kubernetes can take a few seconds to record why a
    runner went away, so a runner that neither answers nor has a verdict is
    asked again until LOST_RUNNER_VERDICT_SEC, then called overloaded and
    kept. Only a 503 deletes the claim here. A dead runner's claim is released
    by the lifecycle controller or replaced by the next start; until then the
    top bar reads degraded.
    """
    deadline = time.monotonic() + _lost_runner_verdict_seconds()
    while True:
        try:
            pod = await get_pod(info["pod_name"])
        except Exception as exc:
            if "404" in str(exc):
                return RUNNER_DIED_MESSAGE
            pod = None
        if pod is not None:
            detail = _oom_detail(pod)
            if not detail:
                evicted = await _eviction_event(pod)
                if evicted:
                    detail = _eviction_detail(evicted)
                    if "memory" not in evicted.lower():
                        return RUNNER_EVICTED_MESSAGE.format(detail=detail)
            if detail:
                return RUNNER_OOM_MESSAGE.format(detail=detail)
            if _pod_dead(pod):
                return RUNNER_DIED_MESSAGE
        if runner_died:
            return RUNNER_DIED_MESSAGE
        health = await _runner_health(info)
        if health == HEALTH_UNHEALTHY:
            await _delete_unhealthy_runner(chat_id, info)
            return RUNNER_DIED_MESSAGE
        if health == HEALTH_OK or time.monotonic() >= deadline:
            return RUNNER_UNREACHABLE_MESSAGE
        await asyncio.sleep(LOST_RUNNER_POLL_SEC)


def _same_runner(a: Optional[dict], b: Optional[dict]) -> bool:
    return bool(a and b) and a.get("pod_name") == b.get("pod_name")


async def _delete_unhealthy_runner(chat_id: str, info: dict) -> None:
    """The runner answered /health with an error: delete its claim now
    rather than wait for the controller. Only this runner's claim (by uid)."""
    hit = _ready_cache.get(chat_id)
    if hit is not None and _same_runner(hit[1], info):
        _drop_runner(chat_id)
    uid = ((info.get("claim") or {}).get("metadata") or {}).get("uid")
    if not uid:
        return
    try:
        await delete_claim(chat_id, uid=uid)
    except Exception:
        log.info("delete unhealthy runner claim failed chat=%s", chat_id, exc_info=True)


# While a chat has tool calls running on a runner, one task per runner polls
# its /health. An explicit error answer (503: its storage disconnected)
# deletes the claim at once, so the running calls fail now instead of when a
# skill next touches its files. A missing answer asks Kubernetes about the
# pod: if its container restarted (an OOM kill), it moved to a new address,
# or it is gone or being deleted, the runner the calls were sent to is dead.
# Its sandbox took the open connections with it without closing them, so the
# calls are failed here rather than left waiting for their timeout. A runner
# that is only slow to answer is left alone. The status check stays read-only.
RUNNER_WATCH_SECONDS = 3.0
_watchers: dict[tuple[str, str], list] = {}


class RunnerLostError(RuntimeError):
    """The runner a tool call was sent to died while the call was running."""


def _container_restarts(pod: Optional[dict]) -> int:
    statuses = ((pod or {}).get("status") or {}).get("containerStatuses") or []
    return sum(int(s.get("restartCount") or 0) for s in statuses)


async def _runner_died_since(info: dict, restarts: Optional[int]) -> Optional[str]:
    """Why the runner the calls were sent to is dead, or None if it may be alive."""
    try:
        pod = await get_pod(info["pod_name"])
    except Exception as exc:
        return "pod gone" if "404" in str(exc) else None
    if _pod_gone_for_good(pod):
        return "pod failed or is being deleted"
    if restarts is not None and _container_restarts(pod) > restarts:
        return "container restarted"
    if _pod_moved(info, pod):
        return "pod moved to a new address"
    return None


async def _watch_runner(chat_id: str, info: dict, lost: asyncio.Event) -> None:
    try:
        restarts = _container_restarts(await get_pod(info["pod_name"]))
    except Exception:
        restarts = None
    while True:
        await asyncio.sleep(RUNNER_WATCH_SECONDS)
        health = await _runner_health(info)
        if health == HEALTH_UNHEALTHY:
            log.info(
                "tool runner unhealthy during a tool call chat=%s runner=%s",
                chat_id,
                _runner_log_name(info),
            )
            await _delete_unhealthy_runner(chat_id, info)
            return
        if health == HEALTH_OK:
            continue
        reason = await _runner_died_since(info, restarts)
        if reason:
            log.info(
                "tool runner died during a tool call chat=%s runner=%s reason=%s",
                chat_id,
                _runner_log_name(info),
                reason,
            )
            hit = _ready_cache.get(chat_id)
            if hit is not None and _same_runner(hit[1], info):
                _drop_runner(chat_id)
            lost.set()
            return


@contextlib.asynccontextmanager
async def _watching_runner(chat_id: str, info: dict):
    """Keep one health watcher running on this runner while any call is in flight."""
    key = (chat_id, info.get("pod_name") or "")
    entry = _watchers.get(key)
    if entry is None or entry[0].done():
        lost = asyncio.Event()
        task = asyncio.create_task(
            _watch_runner(chat_id, info, lost), name=f"runner-watch-{chat_id}"
        )
        entry = [task, 0, lost]
        _watchers[key] = entry
    entry[1] += 1
    try:
        yield entry[2]
    finally:
        entry[1] -= 1
        if entry[1] <= 0:
            entry[0].cancel()
            if _watchers.get(key) is entry:
                _watchers.pop(key, None)


async def exec_on_runner(
    chat_id: str,
    argv: list[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
    timeout: int = 600,
    info: Optional[dict] = None,
) -> dict:
    if info is None:
        info = await ensure_runner(chat_id)
    body = {
        "cmd": argv,
        "cwd": cwd or _runner_workspace(chat_id),
        "env": env or {},
        # The runner stops the skill (and everything it started) at this; chat
        # waits a little longer so the runner's answer arrives first.
        "timeout": timeout,
    }
    base = await _runner_base(info["pod_ip"], info.get("pod_name"), info.get("pod"))
    return await _http_json(
        "POST",
        f"{base}/exec",
        json_body=body,
        timeout=timeout + 15,
    )


async def _unless_runner_lost(lost: asyncio.Event, call) -> dict:
    """The call's result, or RunnerLostError as soon as the watcher sees its
    runner die. The call is cancelled then, which closes its connection."""
    call_task = asyncio.ensure_future(call)
    lost_task = asyncio.ensure_future(lost.wait())
    try:
        done, _ = await asyncio.wait(
            {call_task, lost_task}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        for task in (call_task, lost_task):
            if not task.done():
                task.cancel()
    if call_task in done:
        return call_task.result()
    with contextlib.suppress(BaseException):
        await call_task
    raise RunnerLostError()


def _runner_timed_out(result: dict) -> bool:
    if result.get("timed_out"):
        return True
    # Runner images before timed_out answered exactly this.
    return int(result.get("exit_code", 0)) == -1 and (result.get("stderr") or "").strip() == "timed out"


def _runner_failed_result(message: str, script_path: Path, workspace: str, args: list[str]) -> dict:
    return {
        "ok": False,
        "exit_code": 1,
        "stdout": "",
        "stderr": message,
        "script": script_path.name,
        "cwd": workspace,
        "argv": args,
        "sandlock": False,
        "landlock_backend": None,
        "tool_runner": True,
    }


# Key on a run_skill_on_runner result holding the skill's CPU, peak memory and run time.
TOOL_RUNNER_USAGE_KEY = "tool_runner_usage"
_USAGE_FIELDS = ("cpu_seconds", "peak_memory_bytes", "run_seconds")


def _runner_usage(reply: dict) -> Optional[dict]:
    """The /exec reply's usage, or None when any field is missing, not a finite number, or negative.

    Older runner images send no usage.
    """
    usage = {}
    for field in _USAGE_FIELDS:
        value = reply.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            finite = math.isfinite(value)
        except OverflowError:
            # An int too large for a float.
            return None
        if not finite or value < 0:
            return None
        usage[field] = value
    return usage


def _with_usage(out: dict, reply: dict) -> dict:
    usage = _runner_usage(reply)
    if usage:
        out[TOOL_RUNNER_USAGE_KEY] = usage
    return out


async def run_skill_on_runner(
    *,
    chat_id: str,
    skill_dir: Path,
    script_path: Path,
    args: list[str],
    env: dict[str, str],
    timeout: int,
    emitter=None,
) -> dict:
    from open_webui.utils.skill_runtime import skill_timeout_message

    info = await ensure_runner(chat_id, emitter=emitter)
    await hold_runner_for_skill(chat_id, timeout)
    workspace = _runner_workspace(chat_id)
    remote_script = remote_script_path(skill_dir, script_path)
    argv = ["uv", "run", "--script", remote_script, *args]
    runner_env = {
        "UV_PYTHON_INSTALL_DIR": os.environ.get("UV_PYTHON_INSTALL_DIR", "/opt/uv-python"),
        "UV_CACHE_DIR": _uv_cache_dir(workspace),
        "HOME": workspace,
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
        "CLAUDE_SKILL_DIR": str(Path(remote_script).parent.parent),
        "WEATHER_SKILL_DIR": str(Path(remote_script).parent.parent),
        "WEATHER_INTERMEDIATE_DIR": f"{workspace}/intermediate_results",
        "INTERMEDIATE_RESULTS_DIR": f"{workspace}/intermediate_results",
    }
    runner_env.update(env)
    exec_started = time.monotonic()
    log.info(
        "skill exec start chat=%s script=%s runner=%s",
        chat_id,
        script_path.name,
        _runner_log_name(info),
    )
    try:
        async with _watching_runner(chat_id, info) as lost:
            result = await _unless_runner_lost(
                lost,
                exec_on_runner(
                    chat_id, argv, cwd=workspace, env=runner_env, timeout=timeout, info=info
                ),
            )
    except RunnerLostError:
        log.info(
            "skill exec lost its runner chat=%s script=%s runner=%s elapsed=%.2fs",
            chat_id,
            script_path.name,
            _runner_log_name(info),
            time.monotonic() - exec_started,
        )
        return _runner_failed_result(
            await _lost_exec_message(chat_id, info, runner_died=True),
            script_path,
            workspace,
            args,
        )
    except Exception as exc:
        if isinstance(exc.__cause__, TimeoutError):
            # No answer even after the runner should have stopped the skill.
            # Closing the connection makes the runner stop it if it has not.
            log.info(
                "skill exec timed out chat=%s script=%s runner=%s timeout=%ss",
                chat_id,
                script_path.name,
                _runner_log_name(info),
                timeout,
            )
            return _runner_failed_result(
                skill_timeout_message(timeout), script_path, workspace, args
            )
        log.info(
            "tool runner unreachable chat=%s runner=%s",
            chat_id,
            _runner_log_name(info),
            exc_info=True,
        )
        return _runner_failed_result(
            await _lost_exec_message(chat_id, info), script_path, workspace, args
        )
    if _runner_timed_out(result):
        log.info(
            "skill exec timed out chat=%s script=%s runner=%s timeout=%ss",
            chat_id,
            script_path.name,
            _runner_log_name(info),
            timeout,
        )
        partial = (result.get("stderr") or "").strip()
        if partial == "timed out":  # runner images before timed_out
            partial = ""
        failed = _runner_failed_result(
            skill_timeout_message(timeout), script_path, workspace, args
        )
        failed["exit_code"] = -1
        failed["stdout"] = (result.get("stdout") or "").strip()
        if partial:
            failed["stderr"] += "\n\nSkill stderr before it was stopped:\n" + partial
        return _with_usage(failed, result)
    if (
        int(result.get("exit_code", 1)) != 0
        and await _runner_health(info) == HEALTH_UNHEALTHY
    ):
        # The skill failed and the runner says it is unhealthy (for example its
        # storage disconnected): the runner's fault, not the skill's.
        log.info(
            "tool runner unhealthy after a failed skill chat=%s runner=%s exit=%s",
            chat_id,
            _runner_log_name(info),
            result.get("exit_code"),
        )
        await _delete_unhealthy_runner(chat_id, info)
        return _runner_failed_result(RUNNER_DIED_MESSAGE, script_path, workspace, args)
    log.info(
        "skill exec done chat=%s script=%s runner=%s elapsed=%.2fs exit=%s",
        chat_id,
        script_path.name,
        _runner_log_name(info),
        time.monotonic() - exec_started,
        result.get("exit_code"),
    )
    out = {
        "ok": int(result.get("exit_code", 1)) == 0,
        "exit_code": int(result.get("exit_code", 1)),
        "stdout": (result.get("stdout") or "").strip(),
        "stderr": (result.get("stderr") or "").strip(),
        "script": script_path.name,
        "cwd": workspace,
        "argv": args,
        "sandlock": False,
        "landlock_backend": None,
        "tool_runner": True,
    }
    return _with_usage(out, result)
