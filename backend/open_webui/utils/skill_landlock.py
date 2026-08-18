"""Landlock-only filesystem confinement via direct syscalls.

Used when the sandlock library is unavailable or the host Landlock ABI is below
sandlock's minimum (currently ABI 6). Applies the same read/write path allowlist
model as ``skill_sandlock`` — network is unrestricted.
"""

from __future__ import annotations

import ctypes
import errno
import logging
import os
import platform
import stat
from pathlib import Path
from typing import Sequence


def _is_char_device(path: str) -> bool:
    try:
        return stat.S_ISCHR(os.stat(path, follow_symlinks=False).st_mode)
    except OSError:
        return False


def _needs_dev_write(writable_paths: Sequence[str]) -> bool:
    dev = str(Path("/dev").resolve())
    for path in writable_paths:
        resolved = str(Path(path).resolve())
        if resolved == dev or resolved.startswith(dev + os.sep):
            if _is_char_device(resolved):
                return True
    return False


log = logging.getLogger(__name__)

# landlock_create_ruleset(2) flags
LANDLOCK_CREATE_RULESET_VERSION = 1 << 0

# landlock_add_rule(2) rule types
LANDLOCK_RULE_PATH_BENEATH = 1

# Filesystem access rights (Landlock ABI v1+)
LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
LANDLOCK_ACCESS_FS_REFER = 1 << 13
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14
LANDLOCK_ACCESS_FS_IOCTL_DEV = 1 << 15

READ_ACCESS = (
    LANDLOCK_ACCESS_FS_EXECUTE
    | LANDLOCK_ACCESS_FS_READ_FILE
    | LANDLOCK_ACCESS_FS_READ_DIR
)
WRITE_ACCESS = (
    READ_ACCESS
    | LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_MAKE_SYM
    | LANDLOCK_ACCESS_FS_MAKE_FIFO
    | LANDLOCK_ACCESS_FS_MAKE_SOCK
    | LANDLOCK_ACCESS_FS_MAKE_CHAR
    | LANDLOCK_ACCESS_FS_MAKE_BLOCK
)

PR_SET_NO_NEW_PRIVS = 38

O_PATH = getattr(os, "O_PATH", 0o100000)
O_CLOEXEC = getattr(os, "O_CLOEXEC", 0o2000000)

_LANDLOCK_SYSCALLS = {
    "x86_64": (444, 445, 446),
    "amd64": (444, 445, 446),
    "aarch64": (444, 445, 446),
    "arm64": (444, 445, 446),
}


class LandlockError(Exception):
    """Raised when landlock_only confinement cannot be applied."""


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


class _Landlock:
    def __init__(self) -> None:
        machine = platform.machine().lower()
        syscalls = _LANDLOCK_SYSCALLS.get(machine)
        if syscalls is None:
            raise LandlockError(
                f"unsupported architecture for landlock_only: {machine}"
            )
        (
            self._sys_create_ruleset,
            self._sys_add_rule,
            self._sys_restrict_self,
        ) = syscalls
        self._libc = ctypes.CDLL("libc.so.6", use_errno=True)

    def _syscall(self, number: int, *args: int) -> int:
        arg_types = [ctypes.c_long] * (1 + len(args))
        self._libc.syscall.argtypes = arg_types
        self._libc.syscall.restype = ctypes.c_long
        ret = self._libc.syscall(number, *args)
        if ret == -1:
            err = ctypes.get_errno()
            raise OSError(err, os.strerror(err))
        return int(ret)

    def query_abi(self) -> int:
        try:
            return self._syscall(
                self._sys_create_ruleset,
                0,
                0,
                LANDLOCK_CREATE_RULESET_VERSION,
            )
        except OSError as exc:
            if exc.errno in (errno.ENOSYS, errno.EOPNOTSUPP):
                return -1
            raise LandlockError(f"Landlock ABI probe failed: {exc}") from exc

    def _handled_access_fs(self, abi: int) -> int:
        access = WRITE_ACCESS
        if abi >= 2:
            access |= LANDLOCK_ACCESS_FS_REFER
        if abi >= 3:
            access |= LANDLOCK_ACCESS_FS_TRUNCATE
        if abi >= 5:
            access |= LANDLOCK_ACCESS_FS_IOCTL_DEV
        return access

    def _path_access(self, abi: int, writable: bool) -> int:
        """Rights granted on a PATH_BENEATH rule.

        Handled rights that are not granted here are denied. In particular
        LANDLOCK_ACCESS_FS_REFER must be granted on writable trees or
        rename/link across subdirectories returns EXDEV (uv python installs).
        """
        access = WRITE_ACCESS if writable else READ_ACCESS
        if abi >= 5:
            access |= LANDLOCK_ACCESS_FS_IOCTL_DEV
        if writable:
            if abi >= 2:
                access |= LANDLOCK_ACCESS_FS_REFER
            if abi >= 3:
                access |= LANDLOCK_ACCESS_FS_TRUNCATE
        return access

    def confine(
        self,
        *,
        writable: Sequence[str | Path],
        readable: Sequence[str | Path],
    ) -> None:
        abi = self.query_abi()
        if abi < 1:
            raise LandlockError(f"Landlock ABI {abi} is too old for filesystem rules")

        handled = self._handled_access_fs(abi)
        ruleset_attr = _RulesetAttr(handled_access_fs=handled)
        ruleset_fd = self._syscall(
            self._sys_create_ruleset,
            ctypes.addressof(ruleset_attr),
            ctypes.sizeof(ruleset_attr),
            0,
        )

        writable_paths = [str(Path(p).resolve()) for p in writable if p]
        readable_paths = [str(Path(p).resolve()) for p in readable if p]
        writable_set = set(writable_paths)

        if _needs_dev_write(writable_paths):
            writable_set.add(str(Path("/dev").resolve()))

        seen: set[str] = set()
        rules: list[tuple[str, int]] = []
        for path in readable_paths:
            if path not in seen:
                seen.add(path)
                rules.append((path, self._path_access(abi, path in writable_set)))
        for path in writable_paths:
            if path not in seen:
                seen.add(path)
                rules.append((path, self._path_access(abi, True)))

        for path, access in rules:
            if _is_char_device(path):
                continue
            self._add_path_rule(ruleset_fd, path, access)

        if self._libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            err = ctypes.get_errno()
            raise LandlockError(
                f"prctl(PR_SET_NO_NEW_PRIVS) failed: {os.strerror(err)}"
            )

        try:
            self._syscall(self._sys_restrict_self, ruleset_fd, 0)
        except OSError as exc:
            raise LandlockError(f"landlock_restrict_self failed: {exc}") from exc
        finally:
            os.close(ruleset_fd)

    def _add_path_rule(self, ruleset_fd: int, path: str, access: int) -> None:
        parent_fd = os.open(path, O_PATH | O_CLOEXEC)
        try:
            rule = _PathBeneathAttr(allowed_access=access, parent_fd=parent_fd)
            try:
                self._syscall(
                    self._sys_add_rule,
                    ruleset_fd,
                    LANDLOCK_RULE_PATH_BENEATH,
                    ctypes.addressof(rule),
                    0,
                )
            except OSError as exc:
                raise LandlockError(
                    f"landlock_add_rule failed for {path!r}: {exc}"
                ) from exc
        finally:
            os.close(parent_fd)


_landlock: _Landlock | None = None


def _get_landlock() -> _Landlock:
    global _landlock
    if _landlock is None:
        _landlock = _Landlock()
    return _landlock


def query_landlock_abi() -> int:
    """Return host Landlock ABI version, or -1 when unavailable."""
    try:
        return _get_landlock().query_abi()
    except LandlockError:
        return -1


def landlock_only_available() -> bool:
    return query_landlock_abi() >= 1


def confine_current_process(
    *,
    writable: Sequence[str | Path],
    readable: Sequence[str | Path],
) -> None:
    _get_landlock().confine(writable=writable, readable=readable)
