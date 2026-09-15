"""Chat-scoped local skill venvs with JuiceFS-backed UV_CACHE_DIR.

``UV_CACHE_DIR`` / ``UV_PYTHON_INSTALL_DIR`` stay on the per-user JuiceFS
cache so package downloads persist across chats and pods. Unpacked script
environments live on a local SSD PVC under::

    {SKILL_VENV_ROOT}/{chat_id}/envs/{script_key}/

Created with ``uv venv`` + ``uv export --script`` + ``uv pip install``, then
the skill is run with that venv's interpreter (not ``uv run --script``, which
would ignore a local venv and re-isolate under the cache).

Future (horizontal scale): publish chat_id → pod affinity in Redis so tool
calls land on the replica that already holds that chat's local venvs.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Mapping, Optional

log = logging.getLogger(__name__)

_SAFE_CHAT_ID_RE = __import__("re").compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)
_STAMP_NAME = ".skill-venv-stamp"


class SkillVenvError(RuntimeError):
    """Failed to create or sync a chat-local skill venv."""


def normalize_chat_venv_id(chat_id: Optional[str]) -> str:
    raw = (chat_id or "").strip()
    if not raw or raw in (".", "..") or not _SAFE_CHAT_ID_RE.match(raw):
        raise ValueError(
            "Invalid or missing chat id for skill venv "
            "(expected a short alphanumeric id)."
        )
    if "/" in raw or "\\" in raw or "\x00" in raw:
        raise ValueError("Invalid chat id for skill venv.")
    return raw


def skill_venvs_enabled(*, root: Optional[Path] = None) -> bool:
    """True when a writable skill-venvs root is configured and present."""
    path = Path(root) if root is not None else Path(
        os.environ.get("SKILL_VENV_ROOT", "/var/skill-venvs")
    )
    try:
        return path.is_dir() and os.access(path, os.W_OK)
    except OSError:
        return False


def skill_venv_root(*, root: Optional[Path] = None) -> Path:
    path = Path(root) if root is not None else Path(
        os.environ.get("SKILL_VENV_ROOT", "/var/skill-venvs")
    )
    return path.resolve()


def chat_venv_dir(
    chat_id: str,
    *,
    root: Optional[Path] = None,
) -> Path:
    """Return ``{SKILL_VENV_ROOT}/{chat_id}`` (not created)."""
    safe = normalize_chat_venv_id(chat_id)
    base = skill_venv_root(root=root)
    path = (base / safe).resolve()
    try:
        path.relative_to(base)
    except ValueError as e:
        raise ValueError("Chat venv path escapes the skill-venvs root.") from e
    return path


def script_env_key(script_path: Path) -> str:
    """Stable key for a script's local venv (content + optional ``.lock``)."""
    path = Path(script_path)
    h = hashlib.sha256()
    h.update(path.read_bytes())
    lock = Path(str(path) + ".lock")
    if lock.is_file():
        h.update(b"\0lock\0")
        h.update(lock.read_bytes())
    return h.hexdigest()[:20]


def touch_chat_venv(chat_id: str, *, root: Optional[Path] = None) -> Path:
    """Create/update the chat venv root mtime (LRU key) and return it."""
    chat_root = chat_venv_dir(chat_id, root=root)
    chat_root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    os.utime(chat_root, (now, now))
    return chat_root


def _run_uv(
    args: list[str],
    *,
    env: Mapping[str, str],
    cwd: Optional[Path] = None,
) -> None:
    cmd = ["uv", *args]
    log.info("skill venv: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd,
        env=dict(env),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SkillVenvError(
            f"uv {' '.join(args[:3])} failed (exit {proc.returncode}): {detail[-2000:]}"
        )


def ensure_chat_script_venv(
    chat_id: str,
    script_path: Path,
    *,
    uv_env: Mapping[str, str],
    root: Optional[Path] = None,
) -> Path:
    """Ensure a local venv for *script_path* under the chat dir; return venv path.

    ``uv_env`` must include ``UV_CACHE_DIR`` / ``UV_PYTHON_INSTALL_DIR`` pointing
    at the durable JuiceFS user cache (not the local venv root).
    """
    script_path = Path(script_path).resolve()
    if not script_path.is_file():
        raise SkillVenvError(f"Skill script not found: {script_path}")

    chat_root = touch_chat_venv(chat_id, root=root)
    key = script_env_key(script_path)
    venv_path = (chat_root / "envs" / key).resolve()
    try:
        venv_path.relative_to(chat_root.resolve())
    except ValueError as e:
        raise SkillVenvError("Script venv path escapes chat venv root.") from e

    python = venv_path / "bin" / "python"
    stamp = venv_path / _STAMP_NAME
    if python.is_file() and stamp.is_file():
        try:
            if stamp.read_text(encoding="utf-8").strip() == key:
                return venv_path
        except OSError:
            pass

    venv_path.parent.mkdir(parents=True, exist_ok=True)
    if venv_path.exists():
        shutil.rmtree(venv_path)

    # Keep caller UV_* cache paths; force copy so installs into the local venv
    # from a JuiceFS cache never depend on cross-device hardlinks.
    run_env = {
        **os.environ,
        **dict(uv_env),
        "UV_LINK_MODE": "copy",
        "UV_NO_PROGRESS": "1",
    }

    python_spec = _requires_python_hint(script_path)
    venv_args = ["venv", str(venv_path)]
    if python_spec:
        venv_args.extend(["--python", python_spec])
    _run_uv(venv_args, env=run_env)

    reqs = venv_path / "requirements.script.txt"
    _run_uv(
        [
            "export",
            "--script",
            str(script_path),
            "--no-hashes",
            "-o",
            str(reqs),
        ],
        env=run_env,
    )
    _run_uv(
        [
            "pip",
            "install",
            "--python",
            str(python),
            "-r",
            str(reqs),
        ],
        env=run_env,
    )

    if not python.is_file():
        raise SkillVenvError(f"venv python missing after sync: {python}")
    stamp.write_text(key + "\n", encoding="utf-8")
    touch_chat_venv(chat_id, root=root)
    return venv_path


def _requires_python_hint(script_path: Path) -> Optional[str]:
    """Best-effort PEP 723 requires-python for ``uv venv --python``."""
    try:
        head = script_path.read_text(encoding="utf-8", errors="replace")[:8000]
    except OSError:
        return None
    m = __import__("re").search(
        r"""requires-python\s*=\s*["']([^"']+)["']""",
        head,
    )
    return m.group(1).strip() if m else None


def local_dir_size_bytes(path: Path) -> int:
    """Total size of real files under *path*, not following symlinks."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            dirnames[:] = [
                d
                for d in dirnames
                if not os.path.islink(os.path.join(dirpath, d))
            ]
            for name in filenames:
                fp = os.path.join(dirpath, name)
                if os.path.islink(fp):
                    continue
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    continue
    except OSError:
        return total
    return total


def skill_venv_budget_bytes(
    root: Path,
    *,
    configured_max: Optional[int] = None,
) -> int:
    """Max local bytes to keep; default ~85% of the filesystem capacity."""
    if configured_max is not None and configured_max > 0:
        return configured_max
    env_max = os.environ.get("SKILL_VENV_MAX_BYTES", "").strip()
    if env_max:
        try:
            parsed = int(env_max)
            if parsed > 0:
                return parsed
        except ValueError:
            pass
    try:
        usage = shutil.disk_usage(root)
        return int(usage.total * 0.85)
    except OSError:
        return 0


def lru_cleanup_skill_venvs(
    *,
    root: Optional[Path] = None,
    max_bytes: Optional[int] = None,
    protect_chat_id: Optional[str] = None,
) -> list[str]:
    """Delete oldest chat venv dirs until under budget. Returns removed ids."""
    base = skill_venv_root(root=root)
    if not base.is_dir():
        return []

    budget = skill_venv_budget_bytes(base, configured_max=max_bytes)
    if budget <= 0:
        return []

    protect: str | None = None
    if protect_chat_id:
        try:
            protect = normalize_chat_venv_id(protect_chat_id)
        except ValueError:
            protect = None

    chats: list[tuple[float, str, Path, int]] = []
    try:
        children = list(base.iterdir())
    except OSError:
        return []

    for child in children:
        if not child.is_dir() or child.is_symlink():
            continue
        name = child.name
        if protect and name == protect:
            continue
        try:
            mtime = child.stat().st_mtime
        except OSError:
            continue
        size = local_dir_size_bytes(child)
        chats.append((mtime, name, child, size))

    total = sum(s for *_, s in chats)
    if protect:
        try:
            total += local_dir_size_bytes(chat_venv_dir(protect, root=base))
        except ValueError:
            pass

    if total <= budget:
        return []

    chats.sort(key=lambda row: row[0])  # oldest first
    removed: list[str] = []
    for _mtime, name, path, size in chats:
        if total <= budget:
            break
        try:
            shutil.rmtree(path)
        except OSError as e:
            log.warning("Failed to evict skill venv %s: %s", path, e)
            continue
        total -= size
        removed.append(name)
        log.info(
            "Evicted skill venv chat=%s size_bytes=%s remaining_budget=%s",
            name,
            size,
            budget - total,
        )
    return removed
