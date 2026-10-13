#!/usr/bin/env python3
"""Clone the Weather Skills catalog and uv-install each skill script into UV_CACHE_DIR.

Chat exec uses the same path (/opt/uv-cache). /workspace is an emptyDir, so the
cache cannot live there.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

CATALOG_GIT_URL = "https://github.com/weather-skills/weather-skills-catalog.git"
CATALOG_REF = "main"
DEFAULT_CACHE = "/opt/uv-cache"


def skill_scripts(root: Path):
    for path in sorted(root.rglob("*.py")):
        if "scripts" not in path.parts or "tests" in path.parts:
            continue
        if "# /// script" in path.read_text()[:4096]:
            yield path


def run(cmd: list[str], env: dict[str, str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, env=env)


def prewarm(*, cache_dir: str, python: str = "3.12") -> None:
    url = os.environ.get("CATALOG_GIT_URL", CATALOG_GIT_URL)
    ref = os.environ.get("CATALOG_REF", CATALOG_REF)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "UV_CACHE_DIR": str(cache)}
    with tempfile.TemporaryDirectory(prefix="skill-prewarm-") as tmp:
        catalog = Path(tmp) / "catalog"
        venv = Path(tmp) / "venv"
        req = Path(tmp) / "requirements.txt"
        run(
            ["git", "clone", "--depth", "1", "--branch", ref, url, str(catalog)],
            env,
        )
        run(["uv", "venv", str(venv), "--python", python], env)
        python_bin = str(venv / "bin" / "python")
        scripts = list(skill_scripts(catalog / "skills"))
        if not scripts:
            raise SystemExit(f"no PEP 723 skill scripts under {catalog / 'skills'}")
        for script in scripts:
            print(f"prewarm {script.relative_to(catalog)}", flush=True)
            run(
                [
                    "uv",
                    "export",
                    "--script",
                    str(script),
                    "--no-hashes",
                    "-o",
                    str(req),
                ],
                env,
            )
            run(
                ["uv", "pip", "install", "--python", python_bin, "-r", str(req)],
                env,
            )
    print(f"prewarm complete UV_CACHE_DIR={cache}", flush=True)


def main() -> int:
    prewarm(
        cache_dir=os.environ.get("UV_CACHE_DIR", DEFAULT_CACHE),
        python=os.environ.get("PREWARM_PYTHON", "3.12"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
