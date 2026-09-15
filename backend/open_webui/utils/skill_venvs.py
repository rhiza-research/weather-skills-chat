"""Chat-scoped local uv environments with a JuiceFS-backed package cache.

Skill runs need fast imports (local disk) but durable shared wheels (JuiceFS).
uv stores both under ``UV_CACHE_DIR`` (``environments-v2`` + wheel/archive
dirs). We give each chat a local cache directory whose package layers symlink
into the per-user JuiceFS cache, while ``environments-v2`` stays a real local
directory on a local SSD PVC (dynamically provisioned).

Layout::

    {SKILL_VENV_ROOT}/{chat_id}/uv-cache/
      environments-v2/          # local (venv trees; LRU-evicted with the chat)
      wheels-v*/ -> JuiceFS     # symlinks into user uv-cache
      archive-v*/ -> JuiceFS
      ...

Future (horizontal scale): publish chat_id → pod affinity in Redis so tool
calls land on the replica that already holds that chat's local venvs. Not
wired yet — single replica today.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# uv's cached script/tool environments live here under UV_CACHE_DIR.
ENVIRONMENTS_DIRNAME = "environments-v2"

# Keep in sync with skill_runtime.SAFE_USER_CACHE_ID_RE intent (chat ids are
# UUID-like; reject traversal).
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


def _symlink_to_shared(dest: Path, shared: Path) -> None:
    """Ensure *dest* is a symlink to *shared* (replace wrong links)."""
    if dest.is_symlink():
        try:
            if dest.resolve() == shared.resolve():
                return
        except OSError:
            pass
        dest.unlink()
    elif dest.exists():
        # Real dir/file left behind — leave it; do not destroy local data.
        log.warning(
            "skill venv cache entry %s exists and is not a symlink; leaving it",
            dest,
        )
        return
    dest.symlink_to(shared)


def prepare_chat_uv_cache(
    chat_id: str,
    shared_uv_cache: Path,
    *,
    root: Optional[Path] = None,
) -> Path:
    """Create/refresh a chat-local ``UV_CACHE_DIR`` with JuiceFS package links.

    Returns the chat-local cache path to set as ``UV_CACHE_DIR``.
    """
    shared = Path(shared_uv_cache).resolve()
    shared.mkdir(parents=True, exist_ok=True)

    chat_root = chat_venv_dir(chat_id, root=root)
    chat_root.mkdir(parents=True, exist_ok=True)
    chat_cache = chat_root / "uv-cache"
    chat_cache.mkdir(parents=True, exist_ok=True)

    # Link every shared cache layer except environments (those stay local).
    try:
        shared_entries = list(shared.iterdir())
    except OSError as e:
        log.warning("Could not list shared uv cache %s: %s", shared, e)
        shared_entries = []

    for entry in shared_entries:
        if entry.name == ENVIRONMENTS_DIRNAME:
            continue
        _symlink_to_shared(chat_cache / entry.name, entry)

    env_dir = chat_cache / ENVIRONMENTS_DIRNAME
    if env_dir.is_symlink():
        env_dir.unlink()
    env_dir.mkdir(parents=True, exist_ok=True)

    # LRU key: directory mtime.
    now = time.time()
    os.utime(chat_root, (now, now))
    return chat_cache.resolve()


def local_dir_size_bytes(path: Path) -> int:
    """Total size of real files under *path*, not following symlinks."""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            # Do not descend into symlinked package-cache dirs.
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
