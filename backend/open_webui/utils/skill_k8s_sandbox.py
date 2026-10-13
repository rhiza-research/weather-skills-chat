"""Per-chat tool runner on GKE Agent Sandbox (claim, bind, exec, metrics).

In-cluster (the chat pod) talks to the API with the service-account token and
reaches the bind daemon / runner over the pod network. From a laptop the same
functions use kubectl proxy + port-forward. Config is the SKILL_K8S_* env vars
the chat Helm chart already sets.
"""

from __future__ import annotations

import asyncio
import atexit
import base64
import io
import json
import logging
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


async def _k8s(
    method: str, path: str, body: Optional[dict] = None, timeout: int = 30
) -> dict:
    base, ctx, headers = _api_root()
    if method.upper() == "PATCH":
        headers = {**headers, "Content-Type": "application/merge-patch+json"}
    connector = aiohttp.TCPConnector(ssl=ctx)
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        async with session.request(
            method,
            f"{base}{path}",
            json=body,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            raw = await resp.read()
            if resp.status >= 400:
                raise RuntimeError(f"k8s {method} {path} -> {resp.status}: {raw[:400]!r}")
            return json.loads(raw) if raw else {}


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


async def extend_claim_ttl(claim: dict) -> dict:
    name = claim["metadata"]["name"]
    shutdown = datetime.now(timezone.utc) + timedelta(seconds=_ttl_seconds())
    claim = dict(claim)
    spec = dict(claim.get("spec") or {})
    lifecycle = dict(spec.get("lifecycle") or {})
    lifecycle["shutdownTime"] = shutdown.strftime("%Y-%m-%dT%H:%M:%SZ")
    lifecycle["shutdownPolicy"] = "Delete"
    spec["lifecycle"] = lifecycle
    spec.pop("shutdownTime", None)
    claim["spec"] = spec
    return await _k8s("PUT", _crd("sandboxclaims", name), claim)


async def delete_claim(chat_id: str) -> None:
    try:
        await _k8s("DELETE", _crd("sandboxclaims", claim_name(chat_id)))
    except RuntimeError as exc:
        if "404" in str(exc):
            return
        raise


WAITING_STATUS = "Waiting on weather skills runner"
WAITING_ACTION = "weather_skills_runner"


def public_runner_state(state: Optional[str]) -> str:
    """Map internal runner_status to the top-bar / websocket state."""
    if state in ("ready", "starting"):
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


def _pod_ref(claim: dict) -> Optional[str]:
    status = claim.get("status") or {}
    ref = status.get("sandbox") or status.get("sandboxRef") or status.get("podRef") or {}
    return ref.get("name") or status.get("podName")


async def wait_ready(chat_id: str, timeout: float = 180) -> dict:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await get_claim(chat_id)
        if last and _claim_ready(last) and _pod_ref(last):
            return last
        await asyncio.sleep(1.5)
    raise TimeoutError("Tool runner did not become ready in time")


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


# Baked into the runner image (sandbox/runtime/Dockerfile). /workspace is an
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


def _installed_packs() -> list[Path]:
    root = _skills_dir()
    if not root.is_dir():
        return []
    return sorted(
        path for path in root.iterdir() if path.is_dir() and not path.name.startswith(".")
    )


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


async def _replace_broken_runner(chat_id: str, *, emitter=None) -> dict:
    """Forget a runner we can no longer reach and start another."""
    _drop_runner(chat_id)
    try:
        await delete_claim(chat_id)
    except Exception:
        log.debug("delete claim after broken runner failed", exc_info=True)
    return await ensure_runner(chat_id, emitter=emitter)


def _pack_names(paths: list[Path] | None = None) -> set[str]:
    return {path.name for path in (paths if paths is not None else _installed_packs())}


def _missing_packs(have: set[str]) -> list[Path]:
    return [path for path in _installed_packs() if path.name not in have]


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


async def _packs_ready_on_runner(pod: dict, info: Optional[dict] = None) -> bool:
    anns = (pod.get("metadata") or {}).get("annotations") or {}
    if anns.get(PACKS_ANN) == "ready":
        return True
    if info is None:
        info = _runner_info(pod)
    if not info.get("pod_ip"):
        return False
    have = await _listed_packs(info) or set()
    return _pack_names().issubset(have)


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


async def _ensure_packs_on_runner(info: dict) -> None:
    have = await _listed_packs(info) or set()
    missing = _missing_packs(have)
    if not missing:
        log.info("skill packs already on runner n=%s", len(have))
        return
    started = time.monotonic()
    await asyncio.gather(*[_ensure_pack_on_runner(info, pack) for pack in missing])
    log.info(
        "skill packs ready n=%s missing=%s elapsed=%.2fs",
        len(_installed_packs()),
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
        task = asyncio.create_task(_run_start(chat_id), name=f"runner-start-{chat_id}")
        _starts[chat_id] = task
        return task


async def _run_start(chat_id: str) -> dict:
    cached = _cached_runner(chat_id)
    if cached:
        return cached
    try:
        claim = await get_claim(chat_id)
        if claim is None:
            claim = await create_claim(chat_id)
        elif claim.get("metadata", {}).get("deletionTimestamp"):
            raise RuntimeError("tool runner is shutting down")
        else:
            try:
                claim = await extend_claim_ttl(claim)
            except Exception:
                log.debug("extend ttl failed", exc_info=True)
        claim = await wait_ready(chat_id)
        pod_name = _pod_ref(claim)
        pod = await get_pod(pod_name)
        annotations = (pod.get("metadata") or {}).get("annotations") or {}
        if annotations.get(BOUND_ANN) != chat_id:
            await bind_workspace(chat_id, pod)
            await _annotate_pod(pod, {BOUND_ANN: chat_id})
        pod_ip = (pod.get("status") or {}).get("podIP")
        if not pod_ip:
            raise RuntimeError("tool runner has no pod IP")
        await verify_runtime(pod_ip, pod_name, pod)
        info = {"claim": claim, "pod": pod, "pod_ip": pod_ip, "pod_name": pod_name}
        if not await _packs_ready_on_runner(pod, info):
            await _ensure_packs_on_runner(info)
            await _annotate_pod(pod, {PACKS_ANN: "ready"})
        _store_runner(chat_id, info)
        return info
    except Exception:
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
    await asyncio.wait_for(asyncio.shield(task), timeout=180)


async def ensure_runner(chat_id: str, *, emitter=None) -> dict:
    """Wait for the one start and return the runner. Does not own waiting UI."""
    return await asyncio.shield(start_runner(chat_id))


async def runner_status(chat_id: str) -> dict:
    """Read readiness. Does not start the runner or wait on the start task.

    A ready result is remembered so later status and tool calls do not list
    packs again. Packs are listed only when the pod is not already marked ready.
    """
    name = claim_name(chat_id)
    cached = _cached_runner(chat_id)
    if cached:
        return {"state": "ready", "claim": name}
    claim = await get_claim(chat_id)
    if not claim:
        if _start_in_flight(chat_id):
            return {"state": "starting", "claim": name}
        return {"state": "absent"}
    if not _claim_ready(claim):
        return {"state": "starting", "claim": name}
    try:
        pod = await get_pod(_pod_ref(claim))
    except Exception:
        return {"state": "starting", "claim": name}
    try:
        if await _packs_ready_on_runner(pod):
            pod_ip = (pod.get("status") or {}).get("podIP")
            if pod_ip:
                _store_runner(
                    chat_id,
                    {
                        "claim": claim,
                        "pod": pod,
                        "pod_ip": pod_ip,
                        "pod_name": _pod_ref(claim),
                    },
                )
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
    body = {"cmd": argv, "cwd": cwd or _runner_workspace(chat_id), "env": env or {}}
    base = await _runner_base(info["pod_ip"], info.get("pod_name"), info.get("pod"))
    return await _http_json(
        "POST",
        f"{base}/exec",
        json_body=body,
        timeout=timeout + 15,
    )


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
    info = await ensure_runner(chat_id, emitter=emitter)
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
    try:
        result = await exec_on_runner(
            chat_id, argv, cwd=workspace, env=runner_env, timeout=timeout, info=info
        )
    except Exception:
        log.info("tool runner unreachable chat=%s, replacing", chat_id, exc_info=True)
        info = await _replace_broken_runner(chat_id, emitter=emitter)
        result = await exec_on_runner(
            chat_id, argv, cwd=workspace, env=runner_env, timeout=timeout, info=info
        )
    log.info(
        "skill exec done chat=%s script=%s elapsed=%.2fs exit=%s",
        chat_id,
        script_path.name,
        time.monotonic() - exec_started,
        result.get("exit_code"),
    )
    return {
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
