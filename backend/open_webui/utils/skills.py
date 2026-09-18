"""Install and sync Agent Skills from public git repos into Workspace tools."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yaml

from open_webui.env import SKILLS_DIR, SRC_LOG_LEVELS
from open_webui.internal.db import get_db
from open_webui.models.skill_packs import SkillPack, SkillPackModel, SkillPacks, SkillSummary
from open_webui.models.tools import Tool, ToolForm, ToolMeta, Tools
from open_webui.utils.plugin import load_tool_module_by_id, replace_imports
from open_webui.utils.tools import get_tool_specs

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])

USAGE_MAX_CHARS = 3500
DESC_MAX_CHARS = 800


class SkillInstallError(Exception):
    pass


class SkillInstallBusyError(SkillInstallError):
    """Raised when another install/update/delete is already using git/disk."""


# One checkout at a time: concurrent rmtree/copytree of the same pack (or two
# large packs on JuiceFS) can stall the process long enough for k8s to kill it.
_GIT_OPS_LOCK = threading.Lock()

IGNORE_DIR_NAMES = frozenset(
    {
        ".git",
        ".github",
        "__pycache__",
        ".pytest_cache",
        ".venv",
        "node_modules",
        ".mypy_cache",
        ".ruff_cache",
    }
)
MANIFEST_NAME = ".skillpack-manifest.json"
# Override with SKILL_PACK_COPY_WORKERS. Default is CPU count, capped at 32.
_MAX_COPY_WORKERS = 32


@contextmanager
def exclusive_git_op():
    if not _GIT_OPS_LOCK.acquire(blocking=False):
        raise SkillInstallBusyError(
            "A skill pack install or update is already running. Wait for it to finish."
        )
    try:
        yield
    finally:
        _GIT_OPS_LOCK.release()


@dataclass
class DiscoveredSkill:
    name: str
    description: str
    version: Optional[str]
    skill_dir: Path
    relative_path: str
    usage: str
    scripts: list[str]


def validate_public_git_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise SkillInstallError("git_url is required")
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SkillInstallError("Only public https:// git URLs are supported")
    if not parsed.netloc or not parsed.path:
        raise SkillInstallError("Invalid git URL")
    # Normalize trailing .git / slash
    path = parsed.path.rstrip("/")
    if not path.endswith(".git"):
        path = path + ".git"
    return f"https://{parsed.netloc}{path}"


def sanitize_slug(value: str, fallback: str = "pack") -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = value.strip("-._")
    return value[:80] or fallback


def repo_slug_from_url(git_url: str) -> str:
    path = urlparse(git_url).path.rstrip("/")
    name = path.split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return sanitize_slug(name, "skills")


def pack_dirname(
    git_url: str, git_ref: str, owner_key: Optional[str] = None
) -> str:
    """On-disk folder for a pack checkout.

    Includes a short owner key so two users can install the same url@ref
    without sharing a working tree.
    """
    base = f"{repo_slug_from_url(git_url)}__{sanitize_slug(git_ref, 'ref')}"
    if owner_key:
        return f"{base}__{sanitize_slug(owner_key, 'user')[:16]}"
    return base


def skill_method_name(skill_name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_]+", "_", (skill_name or "").strip())
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if not name:
        name = "skill"
    if name[0].isdigit():
        name = f"skill_{name}"
    return name


def tool_id_for_skill(skill_name: str, pack_slug: str, existing_ids: set[str]) -> str:
    base = f"skill_{skill_method_name(skill_name)}"
    if base not in existing_ids:
        return base
    candidate = f"skill_{sanitize_slug(pack_slug)}_{skill_method_name(skill_name)}"
    if candidate not in existing_ids:
        return candidate
    n = 2
    while True:
        alt = f"{candidate}_{n}"
        if alt not in existing_ids:
            return alt
        n += 1


def _run_git(args: list[str], cwd: Optional[Path] = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except FileNotFoundError as e:
        raise SkillInstallError("`git` is not installed on the server") from e
    except subprocess.TimeoutExpired as e:
        raise SkillInstallError("git command timed out") from e
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise SkillInstallError(err or f"git {' '.join(args)} failed")
    return (result.stdout or "").strip()


def parse_ls_remote(output: str) -> Optional[str]:
    """Pick a commit sha from ``git ls-remote`` output.

    Prefer a peeled ``^{}`` line so annotated tags resolve to the commit.
    """
    peeled = None
    first = None
    for line in (output or "").splitlines():
        parts = line.split()
        if not parts:
            continue
        sha = parts[0].lower()
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            continue
        ref = parts[1] if len(parts) > 1 else ""
        if ref.endswith("^{}"):
            peeled = sha
        elif first is None:
            first = sha
    return peeled or first


def resolve_remote_sha(git_url: str, git_ref: str) -> str:
    """Resolve a branch/tag/sha to a commit without downloading the tree."""
    git_ref = (git_ref or "").strip()
    if not git_ref:
        raise SkillInstallError("git ref (branch/tag/commit) is required")
    if re.fullmatch(r"[0-9a-f]{40}", git_ref, re.I):
        return git_ref.lower()
    for spec in (git_ref, f"refs/heads/{git_ref}", f"refs/tags/{git_ref}"):
        sha = parse_ls_remote(_run_git(["ls-remote", git_url, spec]))
        if sha:
            return sha
    raise SkillInstallError(f"Could not resolve git ref {git_ref!r} on {git_url}")


def _pack_tree_present(local_path: Path) -> bool:
    path = Path(local_path)
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return False


def _skipped_rel(rel: Path) -> bool:
    return rel.as_posix() == MANIFEST_NAME or any(
        part in IGNORE_DIR_NAMES for part in rel.parts
    )


def _file_digest(path: Path) -> str:
    if path.is_symlink():
        return f"symlink:{path.readlink().as_posix()}"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _staging_manifest(staging: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in staging.rglob("*"):
        if not (path.is_symlink() or path.is_file()):
            continue
        rel = path.relative_to(staging)
        if _skipped_rel(rel):
            continue
        files[rel.as_posix()] = _file_digest(path)
    return files


def _load_manifest(dest: Path) -> dict[str, str]:
    manifest_path = dest / MANIFEST_NAME
    if not manifest_path.is_file():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, dict):
        return {}
    return {str(key): str(value) for key, value in files.items()}


def _write_manifest(dest: Path, files: dict[str, str]) -> None:
    payload = json.dumps({"files": files}, sort_keys=True)
    (dest / MANIFEST_NAME).write_text(payload, encoding="utf-8")


def _default_copy_workers() -> int:
    cpus = os.cpu_count() or 1
    return max(1, min(cpus, _MAX_COPY_WORKERS))


def _copy_workers(job_count: int) -> int:
    raw = (os.getenv("SKILL_PACK_COPY_WORKERS") or "").strip()
    if raw:
        try:
            configured = int(raw)
        except ValueError:
            configured = _default_copy_workers()
    else:
        configured = _default_copy_workers()
    configured = max(1, min(configured, _MAX_COPY_WORKERS))
    return max(1, min(configured, job_count))


def _run_parallel(label: str, items: list, fn) -> None:
    if not items:
        return
    workers = _copy_workers(len(items))
    if workers == 1:
        for item in items:
            fn(item)
        return
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=label) as pool:
        futures = [pool.submit(fn, item) for item in items]
        for future in as_completed(futures):
            future.result()


def _remove_path(dest: Path) -> None:
    try:
        dest.unlink()
    except FileNotFoundError:
        return
    except IsADirectoryError:
        shutil.rmtree(dest)


def _copy_regular_file(src: Path, dest: Path) -> None:
    """Truncate-or-create dest without following a dest-side symlink.

    POSIX ``open(O_TRUNC)`` overwrites a regular file in place, which is the
    fast JuiceFS path (no getattr/unlink, no copystat). It cannot replace a
    directory, and without ``O_NOFOLLOW`` it would write *through* a symlink.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(os.fspath(dest), flags, 0o644)
    except OSError:
        if not dest.is_symlink():
            raise
        dest.unlink()
        fd = os.open(os.fspath(dest), flags, 0o644)
    with open(src, "rb") as fsrc, os.fdopen(fd, "wb") as fdst:
        shutil.copyfileobj(fsrc, fdst)


def _copy_file(src: Path, dest: Path) -> None:
    """Overwrite dest with src. ``dest.parent`` must already exist."""
    if src.is_symlink():
        _remove_path(dest)
        dest.symlink_to(src.readlink())
        return
    try:
        _copy_regular_file(src, dest)
    except IsADirectoryError:
        shutil.rmtree(dest)
        _copy_regular_file(src, dest)


def _remove_empty_dirs(root: Path) -> None:
    dirs = sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for path in dirs:
        try:
            path.rmdir()
        except OSError:
            continue


def _unlink_stale(dest: Path, wanted: set[str], previous: dict[str, str]) -> int:
    removed = 0
    for name in IGNORE_DIR_NAMES:
        junk = dest / name
        if junk.is_dir() and not junk.is_symlink():
            shutil.rmtree(junk, ignore_errors=True)
            removed += 1
        elif junk.is_symlink() or junk.is_file():
            junk.unlink()
            removed += 1

    if previous:
        stale = [rel for rel in previous if rel not in wanted]
    else:
        stale = []
        for path in dest.rglob("*"):
            if not (path.is_symlink() or path.is_file()):
                continue
            rel = path.relative_to(dest).as_posix()
            if rel == MANIFEST_NAME or rel in wanted:
                continue
            stale.append(rel)
    stale_paths = [
        dest / rel
        for rel in stale
        if (dest / rel).is_symlink() or (dest / rel).is_file()
    ]
    _run_parallel("skill-pack-unlink", stale_paths, Path.unlink)
    removed += len(stale_paths)
    _remove_empty_dirs(dest)
    return removed


def _publish_working_tree(staging: Path, local_path: Path) -> None:
    """Copy a local checkout onto SKILLS_DIR, writing only files that changed.

    Hashes are computed on the staging tree (local disk). Unchanged files are
    left in place so JuiceFS does not rewrite every blob on each update.
    """
    staging = Path(staging)
    dest = Path(local_path)
    dest.mkdir(parents=True, exist_ok=True)

    wanted = _staging_manifest(staging)
    previous = _load_manifest(dest)
    t0 = time.monotonic()
    copies: list[tuple[Path, Path]] = []
    parents: set[Path] = set()
    for rel, digest in wanted.items():
        dest_file = dest / rel
        if previous.get(rel) == digest and (dest_file.is_file() or dest_file.is_symlink()):
            continue
        copies.append((staging / rel, dest_file))
        parents.add(dest_file.parent)
    # Create parent dirs first so parallel JuiceFS writes do not race mkdir.
    for parent in sorted(parents, key=lambda path: len(path.parts)):
        parent.mkdir(parents=True, exist_ok=True)

    def _copy_pair(pair: tuple[Path, Path]) -> None:
        _copy_file(pair[0], pair[1])

    _run_parallel("skill-pack-copy", copies, _copy_pair)
    removed = _unlink_stale(dest, set(wanted), previous)
    _write_manifest(dest, wanted)
    log.info(
        "Published skill pack tree to %s: copied=%d removed=%d workers=%d in %.1fs",
        dest,
        len(copies),
        removed,
        _copy_workers(len(copies)) if copies else 0,
        time.monotonic() - t0,
    )


def checkout_ref(local_path: Path, git_url: str, git_ref: str) -> str:
    """Shallow-fetch a ref into a local temp dir, then publish the working tree.

    Git runs on local disk (fast; supports hardlinks). Only the checked-out
    files are copied to ``local_path`` — ``.git`` is omitted so durable mounts
    like GCS FUSE / JuiceFS are not flooded with tiny object writes. Returns
    HEAD sha.
    """
    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)
    git_ref = (git_ref or "").strip()
    if not git_ref:
        raise SkillInstallError("git ref (branch/tag/commit) is required")

    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="skill-pack-") as tmp:
        staging = Path(tmp) / "repo"
        staging.mkdir()
        _run_git(["init"], cwd=staging)
        _run_git(["remote", "add", "origin", git_url], cwd=staging)
        _run_git(["fetch", "--depth", "1", "origin", git_ref], cwd=staging)
        _run_git(["checkout", "--force", "FETCH_HEAD"], cwd=staging)
        sha = _run_git(["rev-parse", "HEAD"], cwd=staging)
        log.info(
            "Fetched %s@%s (%s) in %.1fs",
            git_url,
            git_ref,
            sha[:7],
            time.monotonic() - t0,
        )
        _publish_working_tree(staging, local_path)
    return sha


def _parse_skill_md(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except Exception:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    body = parts[2].lstrip("\n")
    return meta, body


def _extract_usage(body: str) -> str:
    # Prefer a ## Usage section; fall back to first fenced code block.
    match = re.search(
        r"(?ims)^##\s+Usage\s*\n(.*?)(?=^##\s|\Z)",
        body,
    )
    if match:
        return match.group(1).strip()[:USAGE_MAX_CHARS]
    fence = re.search(r"```(?:[a-zA-Z0-9_-]+)?\n(.*?)```", body, re.DOTALL)
    if fence:
        return fence.group(0).strip()[:USAGE_MAX_CHARS]
    return body.strip()[:USAGE_MAX_CHARS]


def discover_skills(root: Path) -> list[DiscoveredSkill]:
    root = Path(root).resolve()
    found: list[DiscoveredSkill] = []
    for skill_md in sorted(root.rglob("SKILL.md")):
        skill_dir = skill_md.parent
        # Skip nested .git copies if any
        if ".git" in skill_dir.parts:
            continue
        meta, body = _parse_skill_md(skill_md)
        name = str(meta.get("name") or skill_dir.name).strip()
        description = str(meta.get("description") or name).strip()
        version = None
        metadata = meta.get("metadata") or {}
        if isinstance(metadata, dict):
            version = metadata.get("version")
            if version is not None:
                version = str(version)
        scripts_dir = skill_dir / "scripts"
        scripts = (
            sorted(p.name for p in scripts_dir.glob("*.py") if p.is_file())
            if scripts_dir.is_dir()
            else []
        )
        if not scripts:
            log.warning("Skipping skill without scripts/: %s", skill_dir)
            continue
        relative = skill_dir.relative_to(root).as_posix()
        found.append(
            DiscoveredSkill(
                name=name,
                description=description[:DESC_MAX_CHARS],
                version=version,
                skill_dir=skill_dir,
                relative_path=relative if relative != "." else skill_dir.name,
                usage=_extract_usage(body),
                scripts=scripts,
            )
        )
    return found


def _escape_triple_quotes(text: str) -> str:
    return (text or "").replace('"""', "'''")


def generate_tool_content(
    *,
    method_name: str,
    skill_name: str,
    description: str,
    usage: str,
    skill_dir: Path,
    version: Optional[str],
) -> str:
    doc_lines = [
        description.strip(),
        "",
        f"Skill: {skill_name}"
        + (f" (version {version})" if version else ""),
        "",
        "Usage / CLI flags (pass as argv list of strings):",
        usage.strip(),
        "",
        "Credentials: when this skill needs API keys or tokens from the environment, "
        'pass their secret names via env_secrets (e.g. env_secrets=["ECMWF_API_KEY"]). '
        "Each name is injected as an environment variable with the same name. "
        "Prefer env_secrets over putting {{secret:NAME}} placeholders in argv when "
        "the skill reads os.environ / getenv.",
    ]
    doc = _escape_triple_quotes("\n".join(doc_lines))
    skill_dir_literal = repr(str(skill_dir.resolve()))
    # Token replace — usage text often contains `{...}` braces.
    template = '''\
"""
title: __SKILL_NAME__
author: skill-pack
version: __VERSION__
"""

from open_webui.utils.skill_runtime import run_skill


class Tools:
    def __init__(self):
        self.skill_dir = __SKILL_DIR__

    async def __METHOD_NAME__(
        self,
        argv: list[str] = [],
        script: str = "",
        env_secrets: list[str] = [],
        __user__: dict = {},
        __metadata__: dict = {},
    ) -> dict:
        """
__DOC__

        :param argv: CLI arguments after the script path, e.g. ["--start", "2024-01-01", "--output", "out.zarr"]
        :param script: Optional scripts/ basename when the skill has multiple scripts
        :param env_secrets: Secret names to inject into the process environment (same name as the secret). Example: ["ECMWF_API_KEY"]. Only request secrets this skill needs.
        :return: Structured skill result with exit_code, stdout, and stderr
        """
        return await run_skill(
            self.skill_dir,
            argv=argv or [],
            script=script or None,
            env_secrets=env_secrets or [],
            __user__=__user__,
            __metadata__=__metadata__,
        )
'''
    doc_indented = textwrap.indent(doc, "        ")
    return (
        template.replace("__SKILL_NAME__", skill_name)
        .replace("__VERSION__", version or "0")
        .replace("__SKILL_DIR__", skill_dir_literal)
        .replace("__METHOD_NAME__", method_name)
        .replace("__DOC__", doc_indented)
    )


def _upsert_skill_tool(
    *,
    request_app_tools: dict,
    user_id: str,
    pack: SkillPackModel,
    skill: DiscoveredSkill,
    tool_id: str,
    preserve_access_control: Optional[dict],
    enabled: bool = True,
) -> str:
    method = skill_method_name(skill.name)
    content = generate_tool_content(
        method_name=method,
        skill_name=skill.name,
        description=skill.description,
        usage=skill.usage,
        skill_dir=skill.skill_dir,
        version=skill.version,
    )
    content = replace_imports(content)
    module, _frontmatter = load_tool_module_by_id(tool_id, content=content)
    request_app_tools[tool_id] = module
    specs = get_tool_specs(module)

    manifest = {
        "kind": "skill",
        "pack_id": pack.id,
        "skill_name": skill.name,
        "version": skill.version,
        "git_url": pack.git_url,
        "git_ref": pack.git_ref,
        "commit_sha": pack.commit_sha,
        "skill_dir": str(skill.skill_dir),
        "relative_path": skill.relative_path,
        "scripts": skill.scripts,
        "enabled": bool(enabled),
    }
    meta = ToolMeta(
        description=skill.description,
        manifest=manifest,
    )
    display_name = skill.name
    if skill.version:
        display_name = f"{skill.name}@{skill.version}"

    existing = Tools.get_tool_by_id(tool_id)
    if existing is None:
        Tools.insert_new_tool(
            user_id,
            ToolForm(
                id=tool_id,
                name=display_name,
                content=content,
                meta=meta,
                # None = Public; {} = Private. Do not rewrite None to {}.
                access_control=preserve_access_control,
            ),
            specs,
        )
    else:
        Tools.update_tool_by_id(
            tool_id,
            {
                "name": display_name,
                "content": content,
                "specs": specs,
                "meta": meta.model_dump(),
                # Always mirror pack ACL (including None for Public).
                "access_control": preserve_access_control,
            },
        )
    return tool_id


def _ids_present(db, ids: list[str]) -> set[str]:
    if not ids:
        return set()
    return {tid for (tid,) in db.query(Tool.id).filter(Tool.id.in_(ids)).all()}


def _prepare_skill_tool(
    *,
    pack: SkillPackModel,
    skill: DiscoveredSkill,
    tool_id: str,
    enabled: bool,
    user_id: str,
) -> dict:
    method = skill_method_name(skill.name)
    content = replace_imports(
        generate_tool_content(
            method_name=method,
            skill_name=skill.name,
            description=skill.description,
            usage=skill.usage,
            skill_dir=skill.skill_dir,
            version=skill.version,
        )
    )
    module, _frontmatter = load_tool_module_by_id(tool_id, content=content)
    specs = get_tool_specs(module)
    display_name = skill.name
    if skill.version:
        display_name = f"{skill.name}@{skill.version}"
    meta = ToolMeta(
        description=skill.description,
        manifest={
            "kind": "skill",
            "pack_id": pack.id,
            "skill_name": skill.name,
            "version": skill.version,
            "git_url": pack.git_url,
            "git_ref": pack.git_ref,
            "commit_sha": pack.commit_sha,
            "skill_dir": str(skill.skill_dir),
            "relative_path": skill.relative_path,
            "scripts": skill.scripts,
            "enabled": bool(enabled),
        },
    )
    return {
        "tool_id": tool_id,
        "user_id": user_id,
        "display_name": display_name,
        "content": content,
        "specs": specs,
        "meta": meta.model_dump(),
        "access_control": pack.access_control,
        "enabled": enabled,
        "skill": skill,
        "module": module,
    }


def _sync_pack_tools(
    db,
    pack: SkillPackModel,
    user_id: Optional[str] = None,
) -> tuple[SkillPackModel, dict, set[str]]:
    """Discover skills and stage pack+tool ORM writes on ``db`` (no commit)."""
    root = Path(pack.local_path)
    discovered = discover_skills(root)
    if not discovered:
        raise SkillInstallError(f"No SKILL.md with scripts/ found under {root}")

    pack_row = db.get(SkillPack, pack.id)
    if pack_row is None:
        raise SkillInstallError("Skill pack not found")

    previous = {
        (s.get("skill_name") or s.get("name")): s
        for s in (pack.meta or {}).get("skills") or []
        if isinstance(s, dict)
    }
    pack_slug = pack_dirname(pack.git_url, pack.git_ref, owner_key=pack.user_id)
    prev_ids = [
        s.get("tool_id")
        for s in previous.values()
        if isinstance(s, dict) and s.get("tool_id")
    ]
    candidate_ids = []
    for skill in discovered:
        method = skill_method_name(skill.name)
        candidate_ids.append(f"skill_{method}")
        candidate_ids.append(f"skill_{sanitize_slug(pack_slug)}_{method}")
    occupied = _ids_present(db, prev_ids + candidate_ids)

    used_ids: set[str] = set()
    assignments: list[tuple[DiscoveredSkill, str, dict]] = []
    for skill in discovered:
        prev = previous.get(skill.name) or {}
        tool_id = prev.get("tool_id")
        if tool_id and tool_id in occupied:
            used_ids.add(tool_id)
        else:
            tool_id = tool_id_for_skill(skill.name, pack_slug, occupied | used_ids)
            used_ids.add(tool_id)
            occupied.add(tool_id)
        assignments.append((skill, tool_id, prev))

    owner_id = user_id or pack.user_id
    prepared = []
    summaries: list[dict] = []
    for skill, tool_id, prev in assignments:
        enabled = True if prev.get("enabled") is None else bool(prev.get("enabled"))
        row = _prepare_skill_tool(
            pack=pack,
            skill=skill,
            tool_id=tool_id,
            enabled=enabled,
            user_id=owner_id,
        )
        prepared.append(row)
        summaries.append(
            {
                "name": skill.name,
                "version": skill.version,
                "description": skill.description,
                "tool_id": tool_id,
                "skill_dir": str(skill.skill_dir),
                "relative_path": skill.relative_path,
                "enabled": enabled,
            }
        )

    keep_ids = {s["tool_id"] for s in summaries}
    stale_ids = {
        prev.get("tool_id")
        for prev in previous.values()
        if prev.get("tool_id") and prev.get("tool_id") not in keep_ids
    }

    now = int(time.time())
    existing = {}
    if keep_ids:
        existing = {
            tool.id: tool
            for tool in db.query(Tool).filter(Tool.id.in_(keep_ids)).all()
        }
    new_rows = []
    for row in prepared:
        tool = existing.get(row["tool_id"])
        if tool is None:
            new_rows.append(
                Tool(
                    id=row["tool_id"],
                    user_id=row["user_id"],
                    name=row["display_name"],
                    content=row["content"],
                    specs=row["specs"],
                    meta=row["meta"],
                    access_control=row["access_control"],
                    created_at=now,
                    updated_at=now,
                )
            )
            continue
        tool.name = row["display_name"]
        tool.content = row["content"]
        tool.specs = row["specs"]
        tool.meta = row["meta"]
        tool.access_control = row["access_control"]
        tool.updated_at = now
    if new_rows:
        db.add_all(new_rows)
    if stale_ids:
        db.query(Tool).filter(Tool.id.in_(stale_ids)).delete(synchronize_session=False)

    pack_row.meta = {**(pack_row.meta or {}), "skills": summaries}
    pack_row.updated_at = now
    db.add(pack_row)
    db.flush()
    modules = {row["tool_id"]: row["module"] for row in prepared}
    return SkillPacks._to_model(pack_row), modules, stale_ids


def _commit_pack_tools(
    db,
    pack: SkillPackModel,
    request_app_tools: dict,
    user_id: Optional[str] = None,
) -> SkillPackModel:
    t0 = time.monotonic()
    pack, modules, stale_ids = _sync_pack_tools(db, pack, user_id=user_id)
    db.commit()
    for tool_id in stale_ids:
        request_app_tools.pop(tool_id, None)
    request_app_tools.update(modules)
    log.info(
        "Synced %d skill tools for pack %s in one transaction in %.1fs",
        len(modules),
        pack.id,
        time.monotonic() - t0,
    )
    return pack


def sync_pack_tools(
    pack: SkillPackModel,
    request_app_tools: dict,
    user_id: Optional[str] = None,
) -> SkillPackModel:
    """Discover skills on disk and create/update/remove linked tool rows."""
    with get_db() as db:
        try:
            return _commit_pack_tools(db, pack, request_app_tools, user_id=user_id)
        except Exception:
            db.rollback()
            raise


def resync_all_skill_pack_tools(request_app_tools: dict) -> dict:
    """Regenerate tool wrappers for every installed pack (no git fetch).

    Used on startup / admin resync so schema changes (e.g. env_secrets) land on
    existing installs without requiring a pack update.
    """
    packs = SkillPacks.get_all()
    ok: list[str] = []
    errors: list[dict] = []
    for pack in packs:
        try:
            sync_pack_tools(pack, request_app_tools, user_id=pack.user_id)
            ok.append(pack.id)
        except Exception as e:
            log.exception("Failed to resync skill pack %s", pack.id)
            errors.append({"pack_id": pack.id, "error": str(e)})
    return {"synced": ok, "errors": errors}


def install_skill_pack(
    user_id: str,
    git_url: str,
    git_ref: str,
    request_app_tools: dict,
) -> SkillPackModel:
    url = validate_public_git_url(git_url)
    ref = (git_ref or "main").strip() or "main"

    existing = SkillPacks.get_by_user_url_ref(user_id, url, ref)
    if existing:
        raise SkillInstallError(
            f"You already have this pack installed for {url} @ {ref} "
            f"(id={existing.id}). Use update instead."
        )

    dirname = pack_dirname(url, ref, owner_key=user_id)
    local_path = SKILLS_DIR / dirname

    with exclusive_git_op():
        if local_path.exists():
            shutil.rmtree(local_path)

        sha = checkout_ref(local_path, url, ref)
        name = f"{repo_slug_from_url(url)}@{ref}"
        try:
            with get_db() as db:
                try:
                    pack = SkillPacks.insert(
                        user_id,
                        name=name,
                        git_url=url,
                        git_ref=ref,
                        commit_sha=sha,
                        local_path=str(local_path),
                        meta={"skills": []},
                        db=db,
                    )
                    if not pack:
                        raise SkillInstallError("Failed to create skill pack record")
                    return _commit_pack_tools(
                        db, pack, request_app_tools, user_id=user_id
                    )
                except Exception:
                    db.rollback()
                    raise
        except Exception:
            if local_path.exists():
                shutil.rmtree(local_path, ignore_errors=True)
            raise


def update_skill_pack(
    pack_id: str,
    request_app_tools: dict,
    new_ref: Optional[str] = None,
) -> SkillPackModel:
    pack = SkillPacks.get_by_id(pack_id)
    if not pack:
        raise SkillInstallError("Skill pack not found")

    ref = (new_ref or pack.git_ref).strip()
    if not ref:
        raise SkillInstallError("git ref is required")

    # If retargeting to a ref this user already tracks, refuse
    if ref != pack.git_ref:
        conflict = SkillPacks.get_by_user_url_ref(pack.user_id, pack.git_url, ref)
        if conflict and conflict.id != pack.id:
            raise SkillInstallError(
                f"You already have another pack tracking {pack.git_url} @ {ref}"
            )

    with exclusive_git_op():
        local_path = Path(pack.local_path)
        # If changing ref, optionally move directory to new slug path
        target_path = SKILLS_DIR / pack_dirname(
            pack.git_url, ref, owner_key=pack.user_id
        )
        if ref != pack.git_ref and target_path.resolve() != local_path.resolve():
            if target_path.exists():
                shutil.rmtree(target_path)
            if local_path.exists():
                local_path.rename(target_path)
            local_path = target_path

        remote_sha = None
        try:
            remote_sha = resolve_remote_sha(pack.git_url, ref)
        except SkillInstallError:
            log.warning(
                "Could not resolve %s@%s via ls-remote; fetching",
                pack.git_url,
                ref,
            )

        current_sha = (pack.commit_sha or "").strip().lower()
        if (
            remote_sha
            and remote_sha == current_sha
            and ref == pack.git_ref
            and _pack_tree_present(local_path)
        ):
            log.info(
                "Skill pack %s already at %s; skipping checkout",
                pack.id,
                remote_sha[:7],
            )
            return pack

        sha = checkout_ref(local_path, pack.git_url, ref)
        with get_db() as db:
            try:
                pack = SkillPacks.update(
                    pack.id,
                    {
                        "git_ref": ref,
                        "commit_sha": sha,
                        "local_path": str(local_path),
                        "name": f"{repo_slug_from_url(pack.git_url)}@{ref}",
                    },
                    db=db,
                )
                if not pack:
                    raise SkillInstallError("Skill pack not found after update")
                return _commit_pack_tools(db, pack, request_app_tools)
            except Exception:
                db.rollback()
                raise


def delete_skill_pack(pack_id: str, request_app_tools: dict) -> None:
    pack = SkillPacks.get_by_id(pack_id)
    if not pack:
        raise SkillInstallError("Skill pack not found")
    with exclusive_git_op():
        for s in (pack.meta or {}).get("skills") or []:
            if not isinstance(s, dict):
                continue
            tool_id = s.get("tool_id")
            if tool_id:
                Tools.delete_tool_by_id(tool_id)
                request_app_tools.pop(tool_id, None)
        local_path = Path(pack.local_path)
        if local_path.exists():
            shutil.rmtree(local_path, ignore_errors=True)
        SkillPacks.delete(pack_id)


def set_pack_access_control(
    pack_id: str, access_control: Optional[dict]
) -> SkillPackModel:
    """Set pack ACL and propagate to every linked skill tool."""
    from open_webui.internal.db import get_db
    from open_webui.models.tools import Tool

    pack = SkillPacks.get_by_id(pack_id)
    if not pack:
        raise SkillInstallError("Skill pack not found")

    updated = SkillPacks.update(pack_id, {"access_control": access_control})
    if not updated:
        raise SkillInstallError("Skill pack not found after access update")

    tool_ids = [
        s.get("tool_id")
        for s in (pack.meta or {}).get("skills") or []
        if isinstance(s, dict) and s.get("tool_id")
    ]
    if tool_ids:
        try:
            with get_db() as db:
                tools = db.query(Tool).filter(Tool.id.in_(tool_ids)).all()
                now = int(time.time())
                for tool in tools:
                    tool.access_control = access_control
                    tool.updated_at = now
                db.commit()
        except Exception:
            log.exception(
                "Failed to propagate access_control to tools for pack %s", pack_id
            )

    return updated


def set_skill_enabled(pack_id: str, tool_id: str, enabled: bool) -> SkillPackModel:
    """Toggle a skill's global default enabled flag (chat can still override)."""
    pack = SkillPacks.get_by_id(pack_id)
    if not pack:
        raise SkillInstallError("Skill pack not found")

    meta = dict(pack.meta or {})
    skills = list(meta.get("skills") or [])
    found = False
    for skill in skills:
        if not isinstance(skill, dict):
            continue
        if skill.get("tool_id") == tool_id:
            skill["enabled"] = bool(enabled)
            found = True
            break
    if not found:
        raise SkillInstallError(f"Skill tool {tool_id} not found in pack")

    meta["skills"] = skills
    updated = SkillPacks.update(pack_id, {"meta": meta})
    if not updated:
        raise SkillInstallError("Skill pack not found after enable update")

    tool = Tools.get_tool_by_id(tool_id)
    if tool:
        tool_meta = tool.meta.model_dump() if tool.meta else {}
        manifest = dict(tool_meta.get("manifest") or {})
        if manifest.get("kind") == "skill" or manifest.get("pack_id") == pack_id:
            manifest["enabled"] = bool(enabled)
            tool_meta["manifest"] = manifest
            Tools.update_tool_by_id(tool_id, {"meta": tool_meta})

    return updated


def pack_to_response(pack: SkillPackModel) -> dict:
    skills = [
        SkillSummary.model_validate(s).model_dump()
        if isinstance(s, dict)
        else s.model_dump()
        for s in (
            pack.skills
            or [SkillSummary.model_validate(x) for x in (pack.meta or {}).get("skills") or []]
        )
    ]
    # Prefer nested meta skills if model.skills empty after reload quirks
    if not skills and pack.meta:
        skills = pack.meta.get("skills") or []
    return {
        "id": pack.id,
        "user_id": pack.user_id,
        "name": pack.name,
        "git_url": pack.git_url,
        "git_ref": pack.git_ref,
        "commit_sha": pack.commit_sha,
        "local_path": pack.local_path,
        "meta": pack.meta,
        "access_control": pack.access_control,
        "created_at": pack.created_at,
        "updated_at": pack.updated_at,
        "skills": skills,
    }
