#!/usr/bin/env python3
"""Run a minimal skill through run_skill with the Landlock sandbox, inside the app image.

Exits non-zero unless the skill ran sandboxed and printed its line, and, when
SKILL_LANDLOCK_BACKEND names a backend, ran under that backend. Run from /app/backend so
open_webui imports.
"""

import asyncio
import os
import sys

from open_webui.env import SKILLS_DIR
from open_webui.utils.skill_runtime import run_skill
from open_webui.utils.skill_sandlock import select_landlock_backend

EXPECTED_LINE = "ci-sandbox-check skill ran"

SKILL_SCRIPT = (
    "# /// script\n"
    '# requires-python = ">=3.12,<3.13"\n'
    "# dependencies = []\n"
    "# ///\n"
    f"print({EXPECTED_LINE!r})\n"
)


def main() -> int:
    if select_landlock_backend() is None:
        print("Landlock is unavailable in the container; the skill sandbox cannot run.")
        return 1

    skill_dir = SKILLS_DIR / "ci_sandbox_check" / "skills" / "sandbox-check"
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts" / "main.py").write_text(SKILL_SCRIPT, encoding="utf-8")

    result = asyncio.run(
        run_skill(
            skill_dir,
            argv=["--help"],
            __user__={"id": "ci"},
            __metadata__={"chat_id": "ci-sandbox-check"},
        )
    )
    for key, value in result.items():
        print(f"{key}: {value}")

    failures = []
    if result.get("ok") is not True:
        failures.append("ok is not true")
    if result.get("sandlock") is not True:
        failures.append("sandlock is not true")
    if not result.get("landlock_backend"):
        failures.append("landlock_backend is not set")
    requested = os.environ.get("SKILL_LANDLOCK_BACKEND", "").strip().lower()
    if requested in ("sandlock", "landlock_only") and result.get("landlock_backend") != requested:
        failures.append(f"landlock_backend is not {requested!r}")
    if EXPECTED_LINE not in (result.get("stdout") or ""):
        failures.append(f"stdout does not contain {EXPECTED_LINE!r}")
    if failures:
        print("FAIL: " + "; ".join(failures))
        return 1
    print("PASS: the skill ran under the Landlock sandbox")
    return 0


if __name__ == "__main__":
    sys.exit(main())
