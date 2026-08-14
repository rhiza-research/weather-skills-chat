"""Landlock confinement for skill subprocesses via the sandlock library.

Full ``Sandbox.run()`` (seccomp supervisor) is not relied on here — in some
container environments ``sandlock_create`` fails without extra privileges.
Instead we apply Landlock FS rules with ``sandlock.confine()`` in a child
process, then ``exec`` the skill command. Network is left unrestricted.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional, Sequence

log = logging.getLogger(__name__)

# Host paths skills typically need to read (binaries, certs, resolvers, devices).
DEFAULT_READABLE = (
    "/usr",
    "/etc",
    "/bin",
    "/lib",
    "/lib64",
    "/sbin",
    "/proc",
    "/dev",
)

# Character devices that must be writable (e.g. git redirects to /dev/null).
DEFAULT_WRITABLE_DEVICES = (
    "/dev/null",
    "/dev/zero",
    "/dev/urandom",
    "/dev/random",
    "/dev/tty",
)


def sandlock_available() -> bool:
    try:
        from sandlock import LandlockUnavailableError, landlock_abi_version

        landlock_abi_version()
        return True
    except Exception:
        return False


def build_sandbox(
    *,
    writable: Sequence[str | Path],
    readable: Sequence[str | Path],
    cwd: str | Path | None = None,
):
    """Build a Landlock-only Sandbox (no seccomp supervisor fields)."""
    from sandlock import Sandbox

    writable_paths = [str(Path(p).resolve()) for p in writable if p]
    readable_paths = [str(Path(p).resolve()) for p in readable if p]
    # Deduplicate while preserving order
    seen: set[str] = set()
    readable_dedup: list[str] = []
    for p in [*readable_paths, *writable_paths]:
        if p not in seen:
            seen.add(p)
            readable_dedup.append(p)

    kwargs = {
        "fs_writable": writable_paths,
        "fs_readable": readable_dedup,
        "clean_env": False,
    }
    if cwd is not None:
        kwargs["cwd"] = str(Path(cwd).resolve())
    return Sandbox(**kwargs)


def confine_current_process(
    *,
    writable: Sequence[str | Path],
    readable: Sequence[str | Path],
) -> None:
    from sandlock import confine

    confine(build_sandbox(writable=writable, readable=readable))


def launcher_command(
    *,
    writable: Sequence[str | Path],
    readable: Sequence[str | Path],
    cwd: str | Path,
    argv: Sequence[str],
) -> list[str]:
    """``python -m … --writable … --readable … --cwd … -- cmd``."""
    cmd = [
        sys.executable,
        "-m",
        "open_webui.utils.skill_sandlock",
        "--cwd",
        str(Path(cwd).resolve()),
    ]
    for path in writable:
        cmd.extend(["--writable", str(Path(path).resolve())])
    for path in readable:
        cmd.extend(["--readable", str(Path(path).resolve())])
    cmd.append("--")
    cmd.extend(list(argv))
    return cmd


def _dedupe_paths(paths: Sequence[str | Path]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if not p:
            continue
        s = str(p)
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def skill_pack_readable_roots(
    skill_path: str | Path,
    *,
    skills_root: str | Path | None = None,
) -> list[str]:
    """Ancestors of ``skill_path`` that uv may open (e.g. pack ``pyproject.toml``).

    ``uv run --script`` walks parents of the script looking for a workspace /
    project ``pyproject.toml``. Skill tools pass the per-skill directory
    (``…/pack/skills/name``), but the toml usually lives at the pack root
    (``…/pack/pyproject.toml``). Allow those pack roots read-only without
    opening sibling chat sandboxes under ``artifacts/``.
    """
    root = Path(skill_path).resolve()
    if skills_root is None:
        skills_root = Path(
            os.environ.get("SKILLS_DIR", "/app/backend/data/skills")
        ).resolve()
    else:
        skills_root = Path(skills_root).resolve()
    found: list[str] = []
    for parent in [root, *root.parents]:
        if parent == skills_root:
            break
        try:
            parent.relative_to(skills_root)
        except ValueError:
            break
        if (parent / "pyproject.toml").is_file():
            found.append(str(parent))
    return found


def default_writable_paths(
    *extra: str | Path,
) -> list[str]:
    paths: list[str] = []
    for p in DEFAULT_WRITABLE_DEVICES:
        if Path(p).exists():
            paths.append(p)
    for p in extra:
        if p and Path(p).exists():
            paths.append(str(Path(p).resolve()))
        elif p:
            # Allow callers to pass dirs that will be created before confine.
            paths.append(str(Path(p).resolve()))
    return _dedupe_paths(paths)


def default_readable_paths(extra: Optional[Sequence[str | Path]] = None) -> list[str]:
    paths: list[str] = []
    for p in DEFAULT_READABLE:
        if Path(p).exists():
            paths.append(p)
    for p in extra or ():
        if p and Path(p).exists():
            paths.append(str(Path(p).resolve()))
    # Ensure uv/python dirname is covered even if installed outside /usr
    for binary in ("uv", "python3", "python"):
        resolved = shutil.which(binary)
        if resolved:
            paths.append(str(Path(resolved).resolve().parent))
    return _dedupe_paths(paths)


def _cli_main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Confine with Landlock then exec")
    parser.add_argument("--writable", action="append", default=[])
    parser.add_argument("--readable", action="append", default=[])
    parser.add_argument("--cwd", required=True)
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("skill_sandlock: missing command after --", file=sys.stderr)
        return 2

    cwd = Path(args.cwd).resolve()
    writable = list(args.writable) or default_writable_paths(cwd, "/tmp")
    readable = list(args.readable) or default_readable_paths()

    try:
        confine_current_process(writable=writable, readable=readable)
    except Exception as e:
        print(f"skill_sandlock: failed to confine: {e}", file=sys.stderr)
        return 126

    try:
        os.chdir(cwd)
    except Exception as e:
        print(f"skill_sandlock: chdir failed: {e}", file=sys.stderr)
        return 126

    # Resolve argv[0] before exec so PATH lookups happen under confinement.
    exe = cmd[0]
    if os.sep not in exe and not exe.startswith("."):
        found = shutil.which(exe)
        if not found:
            print(f"skill_sandlock: command not found: {exe}", file=sys.stderr)
            return 127
        cmd[0] = found

    try:
        os.execvpe(cmd[0], cmd, os.environ)
    except FileNotFoundError:
        print(f"skill_sandlock: command not found: {cmd[0]}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    sys.exit(_cli_main())
