#!/usr/bin/env python3
"""Run a Plotly skill that writes a PNG, inside the app image, under Landlock.

The skill installs plotly and kaleido via uv. Kaleido needs Chromium on the
host. Exits non-zero unless each requested backend that this host can run
produced a PNG. SKILL_LANDLOCK_BACKEND, when set to sandlock or landlock_only,
runs only that backend. With no value, both are attempted.
"""

import asyncio
import os
import sys
from pathlib import Path

from open_webui.env import SKILLS_DIR
from open_webui.utils.artifacts import chat_sandbox
from open_webui.utils.skill_runtime import run_skill
from open_webui.utils.skill_sandlock import select_landlock_backend

PNG_NAME = "plotly-check.png"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
CHAT_ID = "ci-plotly-check"

SKILL_SCRIPT = """\
# /// script
# requires-python = ">=3.11"
# dependencies = ["plotly>=6.1.1", "kaleido>=1"]
# ///
from pathlib import Path
import plotly.graph_objects as go

fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[1, 4, 9], mode="lines"))
fig.update_layout(width=320, height=240, margin=dict(l=40, r=20, t=40, b=40))
out = Path("plotly-check.png")
fig.write_image(str(out), format="png")
print(f"wrote {out.resolve()} {out.stat().st_size}")
"""


def _requested_backends() -> list[str]:
    requested = os.environ.get("SKILL_LANDLOCK_BACKEND", "").strip().lower()
    if requested in ("sandlock", "landlock_only"):
        return [requested]
    return ["sandlock", "landlock_only"]


def _run_one(backend: str) -> dict:
    os.environ["SKILL_LANDLOCK_BACKEND"] = backend
    chosen = select_landlock_backend()
    if chosen is None:
        return {"backend": backend, "unavailable": True}

    skill_dir = SKILLS_DIR / "ci_plotly_check" / "skills" / "plotly-check"
    (skill_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (skill_dir / "scripts" / "main.py").write_text(SKILL_SCRIPT, encoding="utf-8")

    png = Path(chat_sandbox(CHAT_ID)) / PNG_NAME
    png.unlink(missing_ok=True)

    result = asyncio.run(
        run_skill(
            skill_dir,
            argv=[],
            timeout=300,
            __user__={"id": "ci"},
            __metadata__={"chat_id": CHAT_ID},
        )
    )
    result["backend"] = backend
    result["png"] = str(png)
    result["png_ok"] = False
    if png.is_file():
        data = png.read_bytes()
        result["png_ok"] = data.startswith(PNG_MAGIC) and len(data) > 256
        result["png_bytes"] = len(data)
    return result


def main() -> int:
    failures: list[str] = []
    ran = 0
    for backend in _requested_backends():
        print(f"=== {backend} ===")
        result = _run_one(backend)
        if result.get("unavailable"):
            print(f"SKIP: {backend} is not usable on this host")
            if backend == "landlock_only":
                failures.append("landlock_only is not usable")
            continue
        for key, value in result.items():
            print(f"{key}: {value}")
        ran += 1
        if result.get("ok") is not True:
            failures.append(f"{backend}: ok is not true")
        if result.get("sandlock") is not True:
            failures.append(f"{backend}: sandlock is not true")
        if result.get("landlock_backend") != backend:
            failures.append(
                f"{backend}: landlock_backend is {result.get('landlock_backend')!r}"
            )
        if not result.get("png_ok"):
            failures.append(f"{backend}: did not write a PNG (install Chromium for Kaleido)")
    if ran == 0:
        failures.append("no Landlock backend could run")
    if failures:
        print("FAIL: " + "; ".join(failures))
        return 1
    print("PASS: Plotly wrote a PNG under Landlock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
