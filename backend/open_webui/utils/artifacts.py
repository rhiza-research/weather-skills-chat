import json
import shutil
from pathlib import Path
from open_webui.env import ARTIFACTS_DIR

ZARR_MARKERS = (".zgroup", ".zarray", "zarr.json")


def chat_sandbox(chat_id: str) -> Path:
    root = (ARTIFACTS_DIR / chat_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_in_sandbox(chat_id: str, relpath: str) -> Path:
    root = chat_sandbox(chat_id)
    target = (root / (relpath or ".")).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes the chat artifact sandbox")
    return target


def is_zarr_store(path: Path) -> bool:
    if not path.is_dir():
        return path.suffix == ".zarr"
    if path.name.endswith(".zarr"):
        return True
    return any((path / marker).exists() for marker in ZARR_MARKERS)


def is_zarr_view(path: Path) -> bool:
    if not path.is_file():
        return False
    if path.name.endswith(".zarrview.json"):
        return True
    if path.suffix != ".json":
        return False
    try:
        data = json.loads(path.read_text())
    except Exception:
        return False
    return isinstance(data, dict) and data.get("type") == "zarr_view"


def read_view(path: Path) -> dict:
    return json.loads(path.read_text())


def classify_entry(path: Path) -> str:
    if is_zarr_store(path):
        return "zarr"
    if is_zarr_view(path):
        return "zarr_view"
    if path.is_dir():
        return "directory"
    return "file"


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def list_artifacts(chat_id: str) -> list[dict]:
    root = chat_sandbox(chat_id)
    entries = []

    def walk(directory: Path):
        for path in sorted(directory.iterdir()):
            rel = path.relative_to(root).as_posix()
            kind = classify_entry(path)
            if kind == "file" and path.suffix.lower() in IMAGE_SUFFIXES:
                kind = "image"
            item = {
                "path": rel,
                "name": path.name,
                "kind": kind,
                "is_dir": path.is_dir(),
                "size": path.stat().st_size if path.is_file() else None,
            }
            if kind == "zarr_view":
                try:
                    spec = read_view(path)
                    zarr_rel = spec.get("zarr") or ""
                    target = resolve_in_sandbox(chat_id, zarr_rel)
                    item["zarr"] = zarr_rel
                    item["title"] = spec.get("title") or path.stem
                    item["missing_zarr"] = not is_zarr_store(target)
                except Exception:
                    item["missing_zarr"] = True
            entries.append(item)
            # Walk directories, but do not descend into zarr stores.
            if path.is_dir() and kind != "zarr":
                walk(path)

    walk(root)
    return entries


def copy_sandbox(src_chat_id: str, dest_chat_id: str) -> None:
    src = (ARTIFACTS_DIR / src_chat_id).resolve()
    dest = chat_sandbox(dest_chat_id)
    if src.exists() and src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)


def delete_sandbox(chat_id: str) -> None:
    root = (ARTIFACTS_DIR / chat_id).resolve()
    if root.exists() and ARTIFACTS_DIR in root.parents:
        shutil.rmtree(root, ignore_errors=True)


def write_bytes(chat_id: str, relpath: str, data: bytes) -> Path:
    target = resolve_in_sandbox(chat_id, relpath)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def write_json(chat_id: str, relpath: str, payload: dict) -> Path:
    target = resolve_in_sandbox(chat_id, relpath)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2))
    return target
