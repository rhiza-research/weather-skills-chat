# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "plotly>=6",
#   "kaleido>=1",
# ]
# ///
"""Render a Plotly PNG through Kaleido so Chromium in the tool-runner image is used."""

from __future__ import annotations

import os
from pathlib import Path

import plotly.graph_objects as go

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
BROWSER = Path(os.environ.get("BROWSER_PATH", "/usr/bin/chromium"))
OUT = Path("plotly-check.png")


def main() -> None:
    if not BROWSER.is_file():
        raise SystemExit(f"chromium missing: {BROWSER}")
    fig = go.Figure(go.Scatter(x=[0, 1], y=[0, 1], mode="lines"))
    fig.update_layout(width=320, height=240, margin=dict(l=20, r=20, t=20, b=20))
    fig.write_image(str(OUT), format="png")
    data = OUT.read_bytes()
    if data[:8] != PNG_MAGIC:
        raise SystemExit(f"not a PNG: {data[:16]!r}")
    print(f"png={OUT.resolve()}")
    print(f"png_bytes={len(data)}")
    print("chromium_ok")


if __name__ == "__main__":
    main()
