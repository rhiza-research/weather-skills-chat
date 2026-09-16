"""Runtime helper used by generated skill tool wrappers."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import signal
from pathlib import Path
from typing import Any, Optional

from open_webui.env import (
    SRC_LOG_LEVELS,
    SKILLS_DIR,
    SKILL_VENV_MAX_BYTES,
    SKILL_VENV_ROOT,
    USER_CACHES_DIR,
    UV_CACHE_DIR,
)
from open_webui.utils.artifacts import chat_sandbox, intermediate_results_dir
from open_webui.utils.skill_venvs import (
    chat_venv_dir,
    ensure_chat_uv_dirs,
    lru_cleanup_skill_venvs,
    skill_venvs_enabled,
)

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

DEFAULT_TIMEOUT_SEC = int(os.getenv("SKILL_RUN_TIMEOUT", "600"))
# Chat-sandboxed skills are Landlock-confined when available (sandlock or landlock_only).
SKILL_SANDLOCK = os.getenv("SKILL_SANDLOCK", "true").lower() in ("1", "true", "yes")
SAFE_SCRIPT_RE = re.compile(r"^[A-Za-z0-9._-]+\.py$")
SAFE_ENV_SECRET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Path segment for DATA_DIR/user_caches/<id> — reject traversal / separators.
SAFE_USER_CACHE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


async def _terminate_skill_process(proc: asyncio.subprocess.Process) -> None:
    """Kill the skill process tree (uv + script children) if still running."""
    if proc.returncode is not None:
        return

    pid = proc.pid
    try:
        if os.name != "nt" and pid:
            # start_new_session=True makes the child the process-group leader.
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                return
            except PermissionError:
                proc.kill()
        else:
            proc.kill()
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (asyncio.TimeoutError, ProcessLookupError):
        pass


def pick_primary_script(scripts_dir: Path) -> str:
    if not scripts_dir.is_dir():
        raise FileNotFoundError(f"No scripts directory at {scripts_dir}")
    py_files = sorted(p.name for p in scripts_dir.glob("*.py") if p.is_file())
    if not py_files:
        raise FileNotFoundError(f"No Python scripts in {scripts_dir}")
    for preferred in ("fetch.py", "main.py", "run.py", "plot.py"):
        if preferred in py_files:
            return preferred
    return py_files[0]


def _resolve_script(skill_dir: Path, script: Optional[str]) -> Path:
    scripts_dir = skill_dir / "scripts"
    name = (script or "").strip() or pick_primary_script(scripts_dir)
    if not SAFE_SCRIPT_RE.match(name):
        raise ValueError(f"Invalid script name: {name}")
    path = (scripts_dir / name).resolve()
    if scripts_dir.resolve() not in path.parents and path.parent != scripts_dir.resolve():
        raise ValueError("Script path escapes the skill scripts directory")
    if not path.is_file():
        raise FileNotFoundError(f"Script not found: {name}")
    return path


def _error_result(message: str, **extra: Any) -> dict:
    return {
        "ok": False,
        "exit_code": extra.get("exit_code", 1),
        "stdout": "",
        "stderr": message,
        **{k: v for k, v in extra.items() if k != "exit_code"},
    }


def normalize_env_secret_names(env_secrets: Optional[list] = None) -> list[str]:
    """Strip, drop empties, dedupe (order preserved). Raises ValueError on bad names."""
    names: list[str] = []
    seen: set[str] = set()
    for raw in env_secrets or []:
        if raw is None:
            continue
        name = str(raw).strip()
        if not name:
            continue
        if not SAFE_ENV_SECRET_RE.match(name):
            raise ValueError(
                f"Invalid env_secrets name {name!r}: use letters, digits, and "
                "underscores only (must start with a letter or underscore)."
            )
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def resolve_env_secrets_for_user(
    names: list[str],
    __user__: Optional[dict] = None,
) -> dict[str, str]:
    """Resolve secret names to plaintext for the calling user.

    Returns a mapping suitable for subprocess env injection.
    Raises ValueError when the user is missing or a secret cannot be used.
    """
    if not names:
        return {}

    from open_webui.models.users import Users
    from open_webui.utils.secrets import resolve_secret_value

    user_id = (__user__ or {}).get("id")
    if not user_id:
        raise ValueError("Cannot inject env_secrets without an authenticated user.")
    user = Users.get_user_by_id(user_id)
    if not user:
        raise ValueError("Cannot inject env_secrets: user not found.")

    resolved: dict[str, str] = {}
    for name in names:
        resolved[name] = resolve_secret_value(user, name)
    return resolved


def _redact_skill_result(result: dict, used_secrets: dict[str, str]) -> dict:
    if not used_secrets:
        return result
    from open_webui.utils.secrets import redact_secrets

    return redact_secrets(result, used_secrets)


def normalize_user_cache_id(user_id: Optional[str]) -> str:
    """Validate a user id for use as a per-user cache directory name."""
    raw = (user_id or "").strip()
    if not raw or raw in (".", "..") or not SAFE_USER_CACHE_ID_RE.match(raw):
        raise ValueError(
            "Invalid or missing user id for skill cache "
            "(expected a short alphanumeric id)."
        )
    if "/" in raw or "\\" in raw or "\x00" in raw:
        raise ValueError("Invalid user id for skill cache.")
    return raw


def user_skill_cache_dir(user_id: str, *, caches_root: Optional[Path] = None) -> Path:
    """Return ``{USER_CACHES_DIR}/{user_id}``, creating it if needed.

    Used as a Landlock-readable/writable root for optional per-user state.
    When ``SKILL_VENV_ROOT`` is mounted, uv cache/python live under the
    per-chat SSD dir instead (see ``ensure_chat_uv_dirs``).
    """
    safe_id = normalize_user_cache_id(user_id)
    root = Path(caches_root) if caches_root is not None else Path(USER_CACHES_DIR)
    path = (root / safe_id).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as e:
        raise ValueError("User cache path escapes the user_caches root.") from e
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_skill_uv_dirs(user_id: str, *, caches_root: Optional[Path] = None) -> tuple[Path, Path]:
    """Return ``(uv_cache_dir, uv_python_dir)`` under the per-user cache root.

    Fallback when chat-local skill-venvs are unavailable. Prefer
    ``ensure_chat_uv_dirs`` when ``SKILL_VENV_ROOT`` is mounted.
    """
    root = user_skill_cache_dir(user_id, caches_root=caches_root)
    uv_cache = root / "uv-cache"
    uv_python = root / "python"
    uv_cache.mkdir(parents=True, exist_ok=True)
    uv_python.mkdir(parents=True, exist_ok=True)
    return uv_cache, uv_python


async def run_skill(
    skill_dir: str | Path,
    argv: Optional[list] = None,
    script: Optional[str] = None,
    env_secrets: Optional[list] = None,
    __user__: Optional[dict] = None,
    __metadata__: Optional[dict] = None,
    timeout: Optional[int] = None,
) -> dict:
    """Run a skill's uv script and return structured stdout/stderr for UI + model."""
    skill_path = Path(skill_dir).resolve()
    if not skill_path.is_dir():
        return _error_result(f"Skill directory not found: {skill_path}")

    try:
        script_path = _resolve_script(skill_path, script)
    except Exception as e:
        return _error_result(f"Skill script error: {e}")

    args = [str(a) for a in (argv or [])]

    try:
        secret_names = normalize_env_secret_names(env_secrets)
        used_secrets = resolve_env_secrets_for_user(secret_names, __user__)
    except ValueError as e:
        return _error_result(
            str(e),
            script=script_path.name,
            argv=args,
            env_secrets=[str(x) for x in (env_secrets or []) if x is not None],
        )

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    use_chat_sandbox = bool(chat_id and chat_id != "local")
    if use_chat_sandbox:
        cwd = chat_sandbox(str(chat_id))
        intermediate = intermediate_results_dir(str(chat_id))
    else:
        cwd = skill_path / ".work"
        cwd.mkdir(parents=True, exist_ok=True)
        intermediate = cwd / "intermediate_results"
        intermediate.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["CLAUDE_SKILL_DIR"] = str(skill_path)
    env["WEATHER_SKILL_DIR"] = str(skill_path)
    env["WEATHER_INTERMEDIATE_DIR"] = str(intermediate)
    env["INTERMEDIATE_RESULTS_DIR"] = str(intermediate)
    env["TMPDIR"] = "/tmp"
    env["HOME"] = str(cwd)
    for name, value in used_secrets.items():
        env[name] = value

    sandboxed = False
    landlock_backend: str | None = None
    user_cache: Path | None = None
    chat_venv_root: Path | None = None
    if use_chat_sandbox and SKILL_SANDLOCK:
        from open_webui.utils.skill_sandlock import (
            default_readable_paths,
            default_writable_paths,
            launcher_command,
            select_landlock_backend,
            skill_pack_readable_roots,
        )

        landlock_backend = select_landlock_backend()
        if landlock_backend is None:
            return _error_result(
                "Skill Landlock sandbox is required for chat sandboxes but "
                "Landlock is unavailable on this host.",
                script=script_path.name,
                cwd=str(cwd),
                argv=args,
            )

        try:
            user_cache = user_skill_cache_dir((__user__ or {}).get("id"))
        except ValueError as e:
            return _error_result(
                str(e),
                script=script_path.name,
                cwd=str(cwd),
                argv=args,
            )

        # Prefer per-chat UV_CACHE_DIR + UV_PYTHON_INSTALL_DIR on the local SSD
        # PVC. uv run --script manages per-script environments there. The two
        # paths must stay distinct (uv can hang under Landlock if equal).
        # Fallback: per-user dirs under USER_CACHES_DIR when skill-venvs is off.
        inner_cmd = ["uv", "run", "--script", str(script_path), *args]
        if skill_venvs_enabled(root=SKILL_VENV_ROOT):
            try:
                lru_cleanup_skill_venvs(
                    root=SKILL_VENV_ROOT,
                    max_bytes=SKILL_VENV_MAX_BYTES or None,
                    protect_chat_id=str(chat_id),
                )
                uv_cache_dir, uv_python_dir = ensure_chat_uv_dirs(
                    str(chat_id),
                    root=SKILL_VENV_ROOT,
                )
                chat_venv_root = chat_venv_dir(str(chat_id), root=SKILL_VENV_ROOT)
            except ValueError as e:
                return _error_result(
                    str(e),
                    script=script_path.name,
                    cwd=str(cwd),
                    argv=args,
                )
        else:
            uv_cache_dir, uv_python_dir = user_skill_uv_dirs(
                (__user__ or {}).get("id")
            )
        env["UV_CACHE_DIR"] = str(uv_cache_dir)
        env["UV_PYTHON_INSTALL_DIR"] = str(uv_python_dir)
        # Same-filesystem chat cache: allow uv's default hardlink/clone. Drop any
        # inherited UV_LINK_MODE=copy from the parent process.
        env.pop("UV_LINK_MODE", None)

        # Per-skill dir + pack root(s) with pyproject.toml (uv walks parents).
        readable_extra = [
            skill_path,
            user_cache,
            *skill_pack_readable_roots(skill_path, skills_root=SKILLS_DIR),
        ]
        if chat_venv_root is not None:
            readable_extra.append(chat_venv_root)
        writable_extra = [cwd, "/tmp", user_cache]
        if chat_venv_root is not None:
            writable_extra.append(chat_venv_root)
        cmd = launcher_command(
            writable=default_writable_paths(*writable_extra),
            readable=default_readable_paths(extra=readable_extra),
            cwd=cwd,
            argv=inner_cmd,
            backend=landlock_backend,
        )
        sandboxed = True
        spawn_cwd = None
    else:
        env["UV_CACHE_DIR"] = str(UV_CACHE_DIR)
        cmd = ["uv", "run", "--script", str(script_path), *args]
        spawn_cwd = str(cwd)

    log_cmd = ["uv", "run", "--script", script_path.name, *args]
    log.info(
        "Running skill script: %s (cwd=%s, sandlock=%s, landlock_backend=%s, "
        "user_cache=%s, chat_venv=%s, env_secrets=%s)",
        " ".join(log_cmd),
        cwd,
        sandboxed,
        landlock_backend,
        str(user_cache) if user_cache else None,
        str(chat_venv_root) if chat_venv_root else None,
        list(used_secrets.keys()),
    )

    spawn_kwargs: dict[str, Any] = {
        "cwd": spawn_cwd,
        "env": env,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }
    # Own process group so Stop/timeout can kill uv and its script children.
    if os.name != "nt":
        spawn_kwargs["start_new_session"] = True

    try:
        proc = await asyncio.create_subprocess_exec(*cmd, **spawn_kwargs)
    except FileNotFoundError:
        return _error_result(
            "Failed to start skill: `uv` is not installed on the server. "
            "Install uv in the container/runtime and retry.",
            script=script_path.name,
            cwd=str(cwd),
        )

    limit = timeout if timeout is not None else DEFAULT_TIMEOUT_SEC
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=limit)
    except asyncio.TimeoutError:
        await _terminate_skill_process(proc)
        return _redact_skill_result(
            _error_result(
                f"Skill timed out after {limit}s: {script_path.name}",
                exit_code=-1,
                script=script_path.name,
                cwd=str(cwd),
                argv=args,
                sandlock=sandboxed,
                landlock_backend=landlock_backend,
            ),
            used_secrets,
        )
    except asyncio.CancelledError:
        # Chat Stop cancels the asyncio task; kill the OS process tree too.
        log.info("Skill cancelled; terminating process tree for %s", script_path.name)
        await _terminate_skill_process(proc)
        raise

    stdout = (stdout_b or b"").decode("utf-8", errors="replace").strip()
    stderr = (stderr_b or b"").decode("utf-8", errors="replace").strip()
    code = proc.returncode if proc.returncode is not None else 1

    if code != 0 and not stderr and not stdout:
        stderr = "Skill failed with no output."

    result = {
        "ok": code == 0,
        "exit_code": code,
        "script": script_path.name,
        "cwd": str(cwd),
        "argv": args,
        "stdout": stdout,
        "stderr": stderr,
        "sandlock": sandboxed,
        "landlock_backend": landlock_backend,
    }
    if user_cache is not None:
        result["user_cache"] = str(user_cache)
    if chat_venv_root is not None:
        result["chat_venv"] = str(chat_venv_root)
    if used_secrets:
        result["env_secrets"] = list(used_secrets.keys())
    return _redact_skill_result(result, used_secrets)
