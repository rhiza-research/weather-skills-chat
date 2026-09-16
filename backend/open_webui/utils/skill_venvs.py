"""Chat-local uv cache + environments on the pod's skill-venvs SSD.

Each replica mounts a generic ephemeral volume at ``SKILL_VENV_ROOT``. Each
chat gets its own uv state under::

    {SKILL_VENV_ROOT}/{chat_id}/
      uv-cache/     # UV_CACHE_DIR (wheels, environments-v2, …)
      python/       # UV_PYTHON_INSTALL_DIR (must differ from uv-cache)

Callers run ``uv run --script`` with those paths. uv manages per-script
environments under ``uv-cache/environments-v2/``. No per-user JuiceFS package
cache and no cross-device ``UV_LINK_MODE=copy``. The disk is pod-lifetime:
lost on reschedule, not shared across replicas.

Future (horizontal scale): publish chat_id → pod affinity in Redis so tool
calls land on the replica that already holds that chat's local cache.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_SAFE_CHAT_ID_RE = __import__("re").compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
)


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


def touch_chat_venv(chat_id: str, *, root: Optional[Path] = None) -> Path:
    """Create/update the chat venv root mtime (LRU key) and return it."""
    chat_root = chat_venv_dir(chat_id, root=root)
    chat_root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    os.utime(chat_root, (now, now))
    return chat_root


def ensure_chat_uv_dirs(
    chat_id: str,
    *,
    root: Optional[Path] = None,
) -> tuple[Path, Path]:
    """Return ``(uv_cache_dir, uv_python_dir)`` under the chat skill-venv root.

    Both directories are created on the local SSD. They must stay distinct —
    uv can hang under Landlock when ``UV_CACHE_DIR`` and
    ``UV_PYTHON_INSTALL_DIR`` are the same path.
    """
    chat_root = touch_chat_venv(chat_id, root=root)
    uv_cache = (chat_root / "uv-cache").resolve()
    uv_python = (chat_root / "python").resolve()
    uv_cache.mkdir(parents=True, exist_ok=True)
    uv_python.mkdir(parents=True, exist_ok=True)
    return uv_cache, uv_python


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
    """Delete oldest chat venv dirs until under budget. Returns removed ids.

    Fast path: if ``shutil.disk_usage(root).used`` is already under budget,
    return immediately without walking chat trees.
    """
    base = skill_venv_root(root=root)
    if not base.is_dir():
        return []

    budget = skill_venv_budget_bytes(base, configured_max=max_bytes)
    if budget <= 0:
        return []

    try:
        used = shutil.disk_usage(base).used
    except OSError:
        used = None
    if used is not None and used <= budget:
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
        if name.startswith("_") or name == "lost+found":
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
