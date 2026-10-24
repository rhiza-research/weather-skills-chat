"""Realistic inputs: sandboxes with provenance, megabyte chats, skill packs."""

from __future__ import annotations

import json
import random
import struct
import zlib
from pathlib import Path

PROVENANCE = [
    {"skill": "dynamical-fetch", "version": "0.0.4", "args": {"dataset": "imerg"}, "input": None},
    {"skill": "aggregate-temporal", "version": "1.2.0", "args": {"window": "weekly"}, "input": "precip.zarr"},
    {"skill": "plot", "version": "1.0.0", "args": {"cmap": "viridis"}, "input": "weekly.zarr"},
]


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png_with_provenance(size_bytes: int = 60_000, seed: int = 0) -> bytes:
    """A valid PNG carrying a weather_skills_history tEXt chunk, padded to a plot's size."""
    rng = random.Random(seed)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    text = b"weather_skills_history\x00" + json.dumps(PROVENANCE).encode()
    pad = bytes(rng.getrandbits(8) for _ in range(max(0, size_bytes - 200)))
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"tEXt", text)
        + _chunk(b"prVt", pad)
        + _chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00"))
        + _chunk(b"IEND", b"")
    )


def build_sandbox(root: Path, entries: int, seed: int = 0) -> None:
    """A chat sandbox shaped like prod's: plots, runs, intermediate data, a Zarr store.

    ``entries`` counts files and folders, as list_artifacts reports them.
    """
    rng = random.Random(seed)
    root.mkdir(parents=True, exist_ok=True)
    folders = [root / "plots", root / "runs", root / "intermediate_results"]
    for folder in folders:
        folder.mkdir(exist_ok=True)
    made = len(folders)
    if entries >= 20:
        store = root / "runs" / "precip.zarr"
        (store / "precip").mkdir(parents=True, exist_ok=True)
        (store / ".zgroup").write_text('{"zarr_format": 2}')
        (store / ".zattrs").write_text(json.dumps({"weather_skills_history": json.dumps(PROVENANCE)}))
        for i in range(8):
            (store / "precip" / f"0.{i}").write_bytes(b"\0" * 4096)
        made += 1
    png = png_with_provenance(seed=seed)
    i = 0
    while made < entries:
        kind = rng.random()
        if kind < 0.45:
            (folders[0] / f"map_{i}.png").write_bytes(png)
        elif kind < 0.55:
            (folders[0] / f"figure_{i}.html").write_text(
                "<html><head><title>figure</title></head><body>" + "x" * 2000 + "</body></html>"
            )
        elif kind < 0.6 and made + 1 < entries:
            sub = folders[1] / f"run_{i}"
            sub.mkdir(exist_ok=True)
            (sub / "summary.json").write_text('{"ok": true}')
            made += 1
        else:
            (folders[rng.randrange(3)] / f"table_{i}.csv").write_text("a,b\n1,2\n" * 50)
        made += 1
        i += 1


def big_chat(target_bytes: int = 1_500_000, user_text: str = "Plot weekly rainfall") -> dict:
    """A chat document the size of a long agent conversation (prod: 1-2 MB)."""
    messages = {}
    previous = None
    i = 0
    size = 0
    while size < target_bytes:
        mid = f"m{i}"
        role = "user" if i % 2 == 0 else "assistant"
        content = user_text if role == "user" else ("Result row, value 12.5 mm. " * 1500)
        messages[mid] = {
            "id": mid,
            "parentId": previous,
            "childrenIds": [],
            "role": role,
            "content": content,
            "timestamp": 1_700_000_000 + i,
        }
        if previous:
            messages[previous]["childrenIds"].append(mid)
        previous = mid
        size += len(content) + 200
        i += 1
    return {
        "title": "Weekly rainfall",
        "models": ["weather-agent"],
        "history": {"currentId": previous, "messages": messages},
        "messages": list(messages.values()),
    }


def build_skill_packs(skills_dir: Path, packs: int = 9, files_per_pack: int = 150) -> list[Path]:
    """Pack checkouts shaped like weather-skills packs: scripts, docs, a lock file."""
    out = []
    rng = random.Random(1)
    for p in range(packs):
        pack = skills_dir / f"pack-{p}__main__{p:08x}"
        for f in range(files_per_pack):
            skill = pack / "skills" / f"skill_{f % 12}"
            skill.mkdir(parents=True, exist_ok=True)
            body = "".join(rng.choice("abcdefghij \n") for _ in range(4000))
            (skill / f"file_{f}.py").write_text(body)
        (pack / "uv.lock").write_text("lock\n" * 2000)
        out.append(pack)
    return out
