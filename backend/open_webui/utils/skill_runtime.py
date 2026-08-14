"""Runtime helper used by generated skill tool wrappers."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS, SKILLS_DIR, UV_CACHE_DIR
from open_webui.utils.artifacts import chat_sandbox, intermediate_results_dir

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

DEFAULT_TIMEOUT_SEC = int(os.getenv("SKILL_RUN_TIMEOUT", "600"))
# Chat-sandboxed skills are Landlock-confined via sandlock when available.
SKILL_SANDLOCK = os.getenv("SKILL_SANDLOCK", "true").lower() in ("1", "true", "yes")
SAFE_SCRIPT_RE = re.compile(r"^[A-Za-z0-9._-]+\.py$")
SAFE_ENV_SECRET_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
    if use_chat_sandbox and SKILL_SANDLOCK:
        from open_webui.utils.skill_sandlock import (
            default_readable_paths,
            default_writable_paths,
            launcher_command,
            sandlock_available,
            skill_pack_readable_roots,
        )

        if not sandlock_available():
            return _error_result(
                "Skill Landlock sandbox (sandlock) is required for chat "
                "sandboxes but is unavailable on this host.",
                script=script_path.name,
                cwd=str(cwd),
                argv=args,
            )

        # Keep uv's cache inside the writable sandbox (not the shared host cache).
        uv_cache = cwd / ".uv-cache"
        uv_cache.mkdir(parents=True, exist_ok=True)
        env["UV_CACHE_DIR"] = str(uv_cache)

        # Per-skill dir + pack root(s) with pyproject.toml (uv walks parents).
        readable_extra = [
            skill_path,
            *skill_pack_readable_roots(skill_path, skills_root=SKILLS_DIR),
        ]
        inner_cmd = ["uv", "run", "--script", str(script_path), *args]
        cmd = launcher_command(
            writable=default_writable_paths(cwd, "/tmp"),
            readable=default_readable_paths(extra=readable_extra),
            cwd=cwd,
            argv=inner_cmd,
        )
        sandboxed = True
        spawn_cwd = None
    else:
        env["UV_CACHE_DIR"] = str(UV_CACHE_DIR)
        cmd = ["uv", "run", "--script", str(script_path), *args]
        spawn_cwd = str(cwd)

    log.info(
        "Running skill script: %s (cwd=%s, sandlock=%s, env_secrets=%s)",
        " ".join(["uv", "run", "--script", script_path.name, *args]),
        cwd,
        sandboxed,
        list(used_secrets.keys()),
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=spawn_cwd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
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
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return _redact_skill_result(
            _error_result(
                f"Skill timed out after {limit}s: {script_path.name}",
                exit_code=-1,
                script=script_path.name,
                cwd=str(cwd),
                argv=args,
                sandlock=sandboxed,
            ),
            used_secrets,
        )

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
    }
    if used_secrets:
        result["env_secrets"] = list(used_secrets.keys())
    return _redact_skill_result(result, used_secrets)
