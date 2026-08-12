"""Runtime helper used by generated skill tool wrappers."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from open_webui.env import SRC_LOG_LEVELS, UV_CACHE_DIR
from open_webui.utils.artifacts import chat_sandbox, intermediate_results_dir

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

DEFAULT_TIMEOUT_SEC = int(os.getenv("SKILL_RUN_TIMEOUT", "600"))
SAFE_SCRIPT_RE = re.compile(r"^[A-Za-z0-9._-]+\.py$")


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


async def run_skill(
    skill_dir: str | Path,
    argv: Optional[list] = None,
    script: Optional[str] = None,
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

    metadata = __metadata__ or {}
    chat_id = metadata.get("chat_id")
    if chat_id and chat_id != "local":
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
    env["UV_CACHE_DIR"] = str(UV_CACHE_DIR)
    env["WEATHER_INTERMEDIATE_DIR"] = str(intermediate)
    env["INTERMEDIATE_RESULTS_DIR"] = str(intermediate)

    cmd = ["uv", "run", "--script", str(script_path), *args]
    log.info("Running skill script: %s (cwd=%s)", " ".join(cmd), cwd)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
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
        return _error_result(
            f"Skill timed out after {limit}s: {script_path.name}",
            exit_code=-1,
            script=script_path.name,
            cwd=str(cwd),
            argv=args,
        )

    stdout = (stdout_b or b"").decode("utf-8", errors="replace").strip()
    stderr = (stderr_b or b"").decode("utf-8", errors="replace").strip()
    code = proc.returncode if proc.returncode is not None else 1

    if code != 0 and not stderr and not stdout:
        stderr = "Skill failed with no output."

    return {
        "ok": code == 0,
        "exit_code": code,
        "script": script_path.name,
        "cwd": str(cwd),
        "argv": args,
        "stdout": stdout,
        "stderr": stderr,
    }
