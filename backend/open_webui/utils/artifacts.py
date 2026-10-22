import asyncio
import functools
import io
import json
import logging
import os
import shutil
import stat
import tarfile
import time
import zipfile
from pathlib import Path
from open_webui.env import ARTIFACTS_DIR
from open_webui.utils.chat_timing import log_timing

log = logging.getLogger(__name__)

ZARR_MARKERS = (".zgroup", ".zarray", "zarr.json")
INTERMEDIATE_RESULTS_DIRNAME = "intermediate_results"
# setgid + ug+rwx so new children inherit this group and stay group-writable.
# Owner matches the tool-runner uid so skills can write files the chat created.
SANDBOX_DIR_MODE = 0o2775
SANDBOX_FILE_MODE = 0o664
SANDBOX_OWNER_UID = 1000
SANDBOX_OWNER_GID = 1000


def own_sandbox_path(path: Path) -> None:
    """Chown/chmod one inode so the runner can read and write it."""
    if path.is_symlink() or not path.exists():
        return
    try:
        os.chown(path, SANDBOX_OWNER_UID, SANDBOX_OWNER_GID)
    except OSError:
        log.debug("could not chown %s", path, exc_info=True)
    mode = SANDBOX_DIR_MODE if path.is_dir() else SANDBOX_FILE_MODE
    try:
        os.chmod(path, mode)
    except OSError:
        log.debug("could not chmod %s", path, exc_info=True)


def own_sandbox_tree(path: Path) -> None:
    """Chown/chmod a file or a directory and everything under it."""
    if path.is_symlink() or not path.exists():
        return
    own_sandbox_path(path)
    if path.is_dir():
        for child in path.iterdir():
            own_sandbox_tree(child)


def make_sandbox_dir(path: Path, root: Path) -> Path:
    """Create a folder that inherits the chat's group and stays group-writable."""
    previous = os.umask(0o002)
    try:
        path.mkdir(parents=True, exist_ok=True)
    finally:
        os.umask(previous)
    root = root.resolve()
    cursor = path.resolve()
    while True:
        own_sandbox_path(cursor)
        if cursor == root or root not in cursor.parents:
            break
        cursor = cursor.parent
    return path


@functools.lru_cache(maxsize=8)
def _artifacts_root(artifacts_dir: Path) -> Path:
    """ARTIFACTS_DIR with symlinks resolved, once per process, not per lookup."""
    return artifacts_dir.resolve()


def _sandbox_prepared(root: Path) -> bool:
    """One stat: intermediate_results exists with the runner's owner and mode.

    chat_sandbox creates it last, so it also means the chat folder is ready.
    Sandboxes made before folders were re-owned fail this and are repaired.
    """
    try:
        info = os.stat(root / INTERMEDIATE_RESULTS_DIRNAME)
    except OSError:
        return False
    return (
        stat.S_ISDIR(info.st_mode)
        and info.st_uid == SANDBOX_OWNER_UID
        and stat.S_IMODE(info.st_mode) == SANDBOX_DIR_MODE
    )


def chat_sandbox(chat_id: str) -> Path:
    t0 = time.perf_counter()
    chat_id = str(chat_id)
    if not chat_id or "/" in chat_id or "\\" in chat_id or chat_id in (".", ".."):
        raise ValueError("Invalid chat id")
    root = _artifacts_root(ARTIFACTS_DIR) / chat_id
    prepared = _sandbox_prepared(root)
    if not prepared:
        make_sandbox_dir(root, root)
        make_sandbox_dir(root / INTERMEDIATE_RESULTS_DIRNAME, root)
    log_timing(
        "juicefs.chat_sandbox",
        time.perf_counter() - t0,
        chat_id=chat_id,
        prepared=prepared,
    )
    return root


def intermediate_results_dir(chat_id: str) -> Path:
    return chat_sandbox(chat_id) / INTERMEDIATE_RESULTS_DIRNAME


def _assert_within(root: Path, target: Path) -> Path:
    target = target.resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes the allowed directory")
    return target


def copy_intermediate_result(
    chat_id: str,
    path: str,
    direction: str,
    destination: str | None = None,
) -> dict:
    """Copy a file/dir between the chat sandbox and intermediate_results.

    direction:
      - "in":  sandbox → intermediate_results
      - "out": intermediate_results → sandbox
    """
    root = chat_sandbox(chat_id)
    intermediate = intermediate_results_dir(chat_id)
    direction = (direction or "").strip().lower()
    if direction not in ("in", "out"):
        raise ValueError("direction must be 'in' or 'out'")

    rel = (path or "").strip().lstrip("/")
    if not rel or rel in (".", INTERMEDIATE_RESULTS_DIRNAME):
        raise ValueError("Provide a relative file or folder path")
    if rel == INTERMEDIATE_RESULTS_DIRNAME or rel.startswith(
        INTERMEDIATE_RESULTS_DIRNAME + "/"
    ):
        raise ValueError(
            f"Do not include '{INTERMEDIATE_RESULTS_DIRNAME}/' in path; "
            "use direction instead"
        )

    dest_rel = (destination or "").strip().lstrip("/") if destination else None
    if dest_rel and (
        dest_rel == INTERMEDIATE_RESULTS_DIRNAME
        or dest_rel.startswith(INTERMEDIATE_RESULTS_DIRNAME + "/")
    ):
        raise ValueError(
            f"Do not include '{INTERMEDIATE_RESULTS_DIRNAME}/' in destination"
        )

    if direction == "in":
        src = _assert_within(root, root / rel)
        if src == intermediate or intermediate in src.parents:
            raise ValueError("Source is already inside intermediate_results")
        dest_name = dest_rel or Path(rel).name
        dest = _assert_within(intermediate, intermediate / dest_name)
    else:
        src = _assert_within(intermediate, intermediate / rel)
        dest_name = dest_rel or Path(rel).name
        dest = _assert_within(root, root / dest_name)
        if dest == intermediate or intermediate in dest.parents:
            raise ValueError("Destination must be outside intermediate_results")

    if not src.exists():
        raise FileNotFoundError(f"Source not found: {rel}")

    make_sandbox_dir(dest.parent, root)
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()

    if src.is_dir():
        shutil.copytree(src, dest)
        own_sandbox_tree(dest)
        kind = "directory"
    else:
        shutil.copy2(src, dest)
        own_sandbox_path(dest)
        kind = "file"

    src_label = (
        rel
        if direction == "in"
        else f"{INTERMEDIATE_RESULTS_DIRNAME}/{rel}"
    )
    dest_label = (
        f"{INTERMEDIATE_RESULTS_DIRNAME}/{dest.relative_to(intermediate).as_posix()}"
        if direction == "in"
        else dest.relative_to(root).as_posix()
    )
    return {
        "ok": True,
        "direction": direction,
        "kind": kind,
        "source": src_label,
        "destination": dest_label,
    }


def resolve_in_sandbox(chat_id: str, relpath: str) -> Path:
    root = chat_sandbox(chat_id)
    target = (root / (relpath or ".")).resolve()
    if target != root and root not in target.parents:
        raise ValueError("Path escapes the chat artifact sandbox")
    return target


def create_folder(chat_id: str, path: str) -> dict:
    """Create a directory (and parents) inside the chat artifact sandbox."""
    rel = (path or "").strip().lstrip("/")
    if not rel or rel in (".",):
        raise ValueError("Provide a relative folder path under the chat sandbox")
    if "\x00" in rel:
        raise ValueError("Invalid path")

    root = chat_sandbox(chat_id)
    target = resolve_in_sandbox(chat_id, rel)
    if target == root:
        raise ValueError("Cannot create the sandbox root itself")

    if target.exists() and not target.is_dir():
        raise FileExistsError(
            f"A non-directory already exists at `{target.relative_to(root).as_posix()}`"
        )

    created = not target.exists()
    make_sandbox_dir(target, root)
    rel_out = target.relative_to(root).as_posix()
    return {
        "ok": True,
        "path": rel_out,
        "created": created,
        "existed": not created,
    }


def is_zarr_store(path: Path) -> bool:
    if not path.is_dir():
        return path.suffix == ".zarr"
    if path.name.endswith(".zarr"):
        return True
    return any((path / marker).exists() for marker in ZARR_MARKERS)


def classify_entry(path: Path) -> str:
    if is_zarr_store(path):
        return "zarr"
    if path.is_dir():
        return "directory"
    return "file"


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
# Interactive pages, such as Plotly figures saved with write_html.
HTML_SUFFIXES = {".html", ".htm"}
PROVENANCE_ATTR_PREFIXES = ("weather_skills_history", "rhiza_history")


def read_png_text_chunks(path: Path) -> dict[str, str]:
    """Read uncompressed tEXt (and decompressed zTXt) key/value pairs from a PNG."""
    import struct
    import zlib

    data = path.read_bytes()
    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return {}

    texts: dict[str, str] = {}
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data):
            break
        chunk = data[start:end]
        offset = end + 4  # skip CRC

        if chunk_type == b"IEND":
            break
        if chunk_type == b"tEXt":
            try:
                key_b, value_b = chunk.split(b"\x00", 1)
                texts[key_b.decode("latin-1")] = value_b.decode("latin-1", errors="replace")
            except ValueError:
                continue
        elif chunk_type == b"zTXt":
            try:
                key_b, rest = chunk.split(b"\x00", 1)
                if not rest:
                    continue
                # method byte then zlib stream
                if rest[0] != 0:
                    continue
                value_b = zlib.decompress(rest[1:])
                texts[key_b.decode("latin-1")] = value_b.decode("utf-8", errors="replace")
            except Exception:
                continue
    return texts


def _is_provenance_key(key: str) -> bool:
    return any(key == prefix or key.startswith(f"{prefix}_") for prefix in PROVENANCE_ATTR_PREFIXES)


def _strip_provenance_png_bytes(data: bytes) -> bytes:
    """Drop weather-skills provenance text chunks from PNG bytes."""
    import struct
    import zlib

    if len(data) < 8 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return data

    out = bytearray(data[:8])
    offset = 8
    while offset + 8 <= len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        start = offset + 8
        end = start + length
        if end + 4 > len(data):
            break
        chunk = data[start:end]
        offset = end + 4

        keep = True
        if chunk_type in (b"tEXt", b"zTXt", b"iTXt"):
            key_b = chunk.split(b"\x00", 1)[0] if b"\x00" in chunk else b""
            key = key_b.decode("latin-1", errors="ignore")
            if _is_provenance_key(key):
                keep = False

        if keep:
            out.extend(struct.pack(">I", len(chunk)))
            out.extend(chunk_type)
            out.extend(chunk)
            crc = zlib.crc32(chunk_type)
            crc = zlib.crc32(chunk, crc) & 0xFFFFFFFF
            out.extend(struct.pack(">I", crc))

        if chunk_type == b"IEND":
            break

    return bytes(out)


def _strip_provenance_from_mapping(obj) -> bool:
    if not isinstance(obj, dict):
        return False
    changed = False
    for key in list(obj.keys()):
        if isinstance(key, str) and _is_provenance_key(key):
            del obj[key]
            changed = True
    return changed


def _strip_provenance_from_zarr_json(path_name: str, data: bytes) -> bytes:
    """Remove provenance attrs from zarr metadata files when present."""
    basename = Path(path_name).name
    if basename not in (".zattrs", ".zmetadata", "zarr.json"):
        return data
    try:
        doc = json.loads(data.decode("utf-8"))
    except Exception:
        return data

    changed = False
    if basename == ".zattrs":
        changed = _strip_provenance_from_mapping(doc)
    elif basename == ".zmetadata":
        attrs = ((doc.get("metadata") or {}).get(".zattrs")) if isinstance(doc, dict) else None
        changed = _strip_provenance_from_mapping(attrs)
    elif basename == "zarr.json" and isinstance(doc, dict):
        changed = _strip_provenance_from_mapping(doc.get("attributes") or doc.get("attrs"))

    if not changed:
        return data
    return json.dumps(doc, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sanitize_output_artifact_bytes(path_name: str, data: bytes) -> bytes:
    """Strip weather-skills provenance when copying execute_code outputs back."""
    if path_name.lower().endswith(".png"):
        return _strip_provenance_png_bytes(data)
    return _strip_provenance_from_zarr_json(path_name, data)


def _skill_names_from_chain(chain) -> list[str]:
    names: list[str] = []
    if not isinstance(chain, list):
        return names
    for entry in chain:
        if not isinstance(entry, dict):
            continue
        skill = entry.get("skill")
        if isinstance(skill, str) and skill.strip():
            names.append(skill.strip())
    return names


def _serialize_input_ref(inp) -> dict | list | None:
    """Shrink input refs for the UI: basename + optional nested history."""
    if inp is None:
        return None
    if isinstance(inp, list):
        return [_serialize_input_ref(item) for item in inp]
    if not isinstance(inp, dict):
        return {"basename": str(inp)}
    out: dict = {}
    basename = inp.get("basename")
    if basename is not None:
        out["basename"] = basename
    elif "path" in inp:
        out["basename"] = Path(str(inp["path"])).name
    if "hash" in inp and inp["hash"] is not None:
        out["hash"] = inp["hash"]
    nested = inp.get("history")
    if isinstance(nested, list) and nested:
        out["history"] = _serialize_chain_steps(nested)
    return out or None


def _serialize_chain_steps(chain) -> list[dict]:
    steps: list[dict] = []
    if not isinstance(chain, list):
        return steps
    for entry in chain:
        if not isinstance(entry, dict):
            continue
        skill = entry.get("skill")
        if not isinstance(skill, str) or not skill.strip():
            continue
        step: dict = {"skill": skill.strip()}
        version = entry.get("version")
        if isinstance(version, str) and version:
            step["version"] = version
        args = entry.get("args")
        if isinstance(args, dict):
            step["args"] = args
        elif args is not None:
            step["args"] = {"value": args}
        else:
            step["args"] = {}
        step["input"] = _serialize_input_ref(entry.get("input"))
        steps.append(step)
    return steps


def _history_label_from_key(key: str) -> str | None:
    for prefix in (
        "weather_skills_history_",
        "rhiza_history_",
    ):
        if key.startswith(prefix):
            label = key[len(prefix) :]
            return label or None
    if key in ("weather_skills_history", "rhiza_history"):
        return None
    return None


def _parse_history_chains_from_text_map(texts: dict[str, str]) -> list[dict]:
    """Build labeled provenance branches from a key→JSON map (PNG tEXt or attrs)."""
    branches: list[dict] = []
    for key in sorted(texts.keys()):
        is_hist = key == "weather_skills_history" or key.startswith(
            "weather_skills_history_"
        )
        is_legacy = key == "rhiza_history" or key.startswith("rhiza_history_")
        if not (is_hist or is_legacy):
            continue
        try:
            parsed = json.loads(texts[key])
        except Exception:
            continue
        steps = _serialize_chain_steps(parsed)
        if not steps:
            continue
        branches.append(
            {
                "label": _history_label_from_key(key),
                "steps": steps,
                "crumbs": _skill_names_from_chain(parsed),
            }
        )
    return branches


def _provenance_payload(branches: list[dict]) -> dict | None:
    if not branches:
        return None
    # Flat crumbs: longest branch (stable breadcrumb for compact display).
    crumbs = max((b.get("crumbs") or [] for b in branches), key=len, default=[])
    return {"crumbs": crumbs, "branches": branches}


def provenance_for_png(path: Path) -> dict | None:
    try:
        texts = read_png_text_chunks(path)
    except Exception:
        return None
    return _provenance_payload(_parse_history_chains_from_text_map(texts))


# Provenance <meta> tags sit in the page head; an embedded Plotly page can be
# many MB after it, so only the start of the file is read.
HTML_HEAD_MAX_BYTES = 1024 * 1024


def read_html_meta_texts(path: Path) -> dict[str, str]:
    """weather_skills_history <meta name=... content=...> values from a page head."""
    from html.parser import HTMLParser

    texts: dict[str, str] = {}

    class _Head(HTMLParser):
        done = False

        def handle_starttag(self, tag, attrs):
            if self.done:
                return
            if tag == "body":
                self.done = True
                return
            if tag != "meta":
                return
            values = dict(attrs)
            name = values.get("name") or ""
            content = values.get("content")
            if content is not None and _is_provenance_key(name):
                texts[name] = content

        def handle_endtag(self, tag):
            if tag == "head":
                self.done = True

    parser = _Head(convert_charrefs=True)
    with path.open("rb") as f:
        data = f.read(HTML_HEAD_MAX_BYTES)
    end = data.lower().find(b"</head>")
    if end >= 0:
        data = data[: end + len(b"</head>")]
    parser.feed(data.decode("utf-8", errors="replace"))
    return texts


def provenance_for_html(path: Path) -> dict | None:
    try:
        texts = read_html_meta_texts(path)
    except Exception:
        return None
    return _provenance_payload(_parse_history_chains_from_text_map(texts))


def _read_zarr_attr_texts(path: Path) -> dict[str, str]:
    """Best-effort read of weather_skills_history attrs without opening via xarray."""
    texts: dict[str, str] = {}

    def _absorb(attrs: dict):
        if not isinstance(attrs, dict):
            return
        for key, value in attrs.items():
            if not isinstance(key, str):
                continue
            if not (
                key == "weather_skills_history"
                or key.startswith("weather_skills_history_")
                or key == "rhiza_history"
                or key.startswith("rhiza_history_")
            ):
                continue
            if isinstance(value, (dict, list)):
                texts[key] = json.dumps(value)
            elif isinstance(value, str):
                texts[key] = value

    zattrs = path / ".zattrs"
    if zattrs.is_file():
        try:
            _absorb(json.loads(zattrs.read_text()))
        except Exception:
            pass

    zmetadata = path / ".zmetadata"
    if zmetadata.is_file() and not texts:
        try:
            meta = json.loads(zmetadata.read_text())
            _absorb((meta.get("metadata") or {}).get(".zattrs") or {})
        except Exception:
            pass

    zarr_json = path / "zarr.json"
    if zarr_json.is_file() and not texts:
        try:
            meta = json.loads(zarr_json.read_text())
            _absorb(meta.get("attributes") or meta.get("attrs") or {})
        except Exception:
            pass

    return texts


def provenance_for_zarr(path: Path) -> dict | None:
    try:
        texts = _read_zarr_attr_texts(path)
    except Exception:
        return None
    return _provenance_payload(_parse_history_chains_from_text_map(texts))


def provenance_crumbs_for_path(path: Path) -> list[str]:
    """Return oldest-first skill names from weather_skills_history, or []."""
    payload = provenance_for_png(path) if path.is_file() else None
    if not payload:
        return []
    return list(payload.get("crumbs") or [])


def list_artifacts(
    chat_id: str,
    path: str | None = None,
    depth: int | None = None,
    provenance: bool = True,
) -> list[dict]:
    """List a chat's sandbox. Blocks on JuiceFS; async code uses list_artifacts_async.

    path: only the entry at this relative path and everything under it, exactly
    as if the full listing were filtered by path. Folders that do not lead to
    it are not walked. Paths in the result stay relative to the sandbox root.
    depth: how many folder levels to list below path, or below the root
    (1 = direct contents). Folders at the limit are listed with ``truncated``
    set. None lists every level.
    provenance: read provenance from images, HTML pages and Zarr stores. Each
    read opens the file, so turning it off makes large listings much cheaper.
    """
    if depth is not None and depth < 1:
        raise ValueError("depth must be at least 1")
    t0 = time.perf_counter()
    root = chat_sandbox(chat_id)
    prefix = path or ""
    base = prefix.rstrip("/")
    base_levels = len(base.split("/")) if base else 0
    entries = []

    def walk(directory: Path):
        for path in sorted(directory.iterdir()):
            # Hide dotfiles/dirs (uv cache, HOME scratch under Landlock, etc.)
            if path.name.startswith("."):
                continue
            rel = path.relative_to(root).as_posix()
            if prefix and rel != prefix and not rel.startswith(base + "/"):
                # Outside the requested path: only walk on toward it.
                if (
                    prefix.startswith(rel + "/")
                    and path.is_dir()
                    and not is_zarr_store(path)
                ):
                    walk(path)
                continue
            kind = classify_entry(path)
            if kind == "file" and path.suffix.lower() in IMAGE_SUFFIXES:
                kind = "image"
            elif kind == "file" and path.suffix.lower() in HTML_SUFFIXES:
                kind = "html"
            is_file = path.is_file()
            stat = path.stat() if is_file else None
            item = {
                "path": rel,
                "name": path.name,
                "kind": kind,
                "is_dir": path.is_dir(),
                "size": stat.st_size if stat else None,
                # Lets an open preview notice the file was rewritten.
                "modified": int(stat.st_mtime * 1000) if stat else None,
            }
            prov = None
            if provenance:
                if kind == "image" and path.suffix.lower() == ".png":
                    prov = provenance_for_png(path)
                elif kind == "html":
                    prov = provenance_for_html(path)
                elif kind == "zarr":
                    prov = provenance_for_zarr(path)
            if prov:
                # crumbs kept for compact labels; branches carry full args.
                item["provenance"] = prov.get("crumbs") or []
                item["provenance_detail"] = prov
            # Walk directories, but do not descend into zarr stores.
            descend = path.is_dir() and kind != "zarr"
            level = rel.count("/") + 1 - base_levels
            if descend and depth is not None and level >= depth:
                item["truncated"] = True
                descend = False
            entries.append(item)
            if descend:
                walk(path)

    walk(root)
    log_timing(
        "juicefs.list_artifacts",
        time.perf_counter() - t0,
        chat_id=chat_id,
        n=len(entries),
        depth=depth,
        provenance=provenance,
    )
    return entries


async def list_artifacts_async(
    chat_id: str,
    path: str | None = None,
    depth: int | None = None,
    provenance: bool = True,
) -> list[dict]:
    """list_artifacts on a worker thread, so the walk never blocks the event loop."""
    return await asyncio.to_thread(
        list_artifacts, chat_id, path=path, depth=depth, provenance=provenance
    )


def _copy_sandbox_entry(src: Path, dest: Path) -> None:
    """Copy a file or directory. Symlinks are kept as links, not followed."""
    if src.is_symlink():
        if dest.is_symlink() or dest.exists():
            if dest.is_dir() and not dest.is_symlink():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        dest.symlink_to(src.readlink())
        return
    if src.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        own_sandbox_path(dest)
        for child in src.iterdir():
            _copy_sandbox_entry(child, dest / child.name)
        return
    if src.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        own_sandbox_path(dest.parent)
        dest.write_bytes(src.read_bytes())
        own_sandbox_path(dest)


def copy_sandbox(src_chat_id: str, dest_chat_id: str) -> None:
    """Copy visible sandbox files onto dest.

    Root dot entries (``.local``, ``.cache``, and similar HOME scratch) are
    skipped. Dotfiles inside a copied directory, such as zarr ``.zarray``,
    are kept. Each top-level entry is copied on its own so one failure does
    not drop the rest.
    """
    t0 = time.perf_counter()
    src = (ARTIFACTS_DIR / str(src_chat_id)).resolve()
    dest = chat_sandbox(str(dest_chat_id))
    artifacts_root = ARTIFACTS_DIR.resolve()
    if (
        src != dest
        and src.is_dir()
        and artifacts_root in src.parents
    ):
        for entry in src.iterdir():
            if entry.name.startswith("."):
                continue
            try:
                _copy_sandbox_entry(entry, dest / entry.name)
            except Exception:
                log.exception(
                    "Failed to copy sandbox entry %s from %s to %s",
                    entry.name,
                    src_chat_id,
                    dest_chat_id,
                )
        make_sandbox_dir(dest / INTERMEDIATE_RESULTS_DIRNAME, dest)
    log_timing(
        "juicefs.copy_sandbox",
        time.perf_counter() - t0,
        src_chat_id=src_chat_id,
        dest_chat_id=dest_chat_id,
    )


def delete_sandbox(chat_id: str) -> None:
    root = (ARTIFACTS_DIR / chat_id).resolve()
    if root.exists() and ARTIFACTS_DIR in root.parents:
        shutil.rmtree(root, ignore_errors=True)


def write_bytes(chat_id: str, relpath: str, data: bytes) -> Path:
    t0 = time.perf_counter()
    target = resolve_in_sandbox(chat_id, relpath)
    make_sandbox_dir(target.parent, chat_sandbox(chat_id))
    target.write_bytes(data)
    own_sandbox_path(target)
    log_timing(
        "juicefs.write_bytes",
        time.perf_counter() - t0,
        chat_id=chat_id,
        bytes=len(data),
        relpath=relpath,
    )
    return target


def copy_upload_into_chat_sandbox(chat_id: str, filename: str, data: bytes) -> str:
    """Write an uploaded file at the sandbox root (skills cwd) under a safe basename."""
    name = Path(filename or "upload").name.replace("\x00", "").strip()
    if not name or name in (".", ".."):
        name = "upload"
    dest = write_bytes(chat_id, name, data)
    return dest.relative_to(chat_sandbox(chat_id)).as_posix()


EXECUTE_CODE_MAX_ARCHIVE_BYTES = 50 * 1024 * 1024


def normalize_sandbox_relpath(path: str) -> str:
    rel = (path or "").strip().replace("\\", "/").lstrip("/")
    if not rel or rel in (".",):
        raise ValueError("Provide a relative artifact path")
    if "\x00" in rel:
        raise ValueError("Invalid path")
    parts = Path(rel).parts
    if any(part in ("", "..") for part in parts):
        raise ValueError("Path escapes the chat artifact sandbox")
    return Path(*parts).as_posix()


def sandbox_tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    if not path.exists():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file() and not child.is_symlink():
            total += child.stat().st_size
    return total


def _tar_add_filter(tarinfo: tarfile.TarInfo):
    if tarinfo.issym() or tarinfo.islnk():
        return None
    return tarinfo


def _safe_tar_member_name(name: str) -> str:
    cleaned = (name or "").replace("\\", "/").lstrip("/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    if not cleaned or cleaned in (".",):
        raise ValueError("Invalid archive member path")
    return normalize_sandbox_relpath(cleaned)


def pack_sandbox_archive(chat_id: str, paths: list[str]) -> bytes:
    """Gzip-tar one or more sandbox files/directories (includes zarr internals)."""
    if not paths:
        raise ValueError("Provide at least one path to archive")
    resolved: list[tuple[str, Path]] = []
    total = 0
    seen: set[str] = set()
    for raw in paths:
        rel = normalize_sandbox_relpath(raw)
        if rel in seen:
            continue
        seen.add(rel)
        target = resolve_in_sandbox(chat_id, rel)
        if not target.exists():
            raise FileNotFoundError(f"Artifact not found: {rel}")
        total += sandbox_tree_size(target)
        if total > EXECUTE_CODE_MAX_ARCHIVE_BYTES:
            raise ValueError(
                f"Selected files exceed the {EXECUTE_CODE_MAX_ARCHIVE_BYTES} byte limit"
            )
        resolved.append((rel, target))

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel, target in resolved:
            tar.add(
                target,
                arcname=rel,
                recursive=True,
                filter=_tar_add_filter,
            )
    data = buf.getvalue()
    if len(data) > EXECUTE_CODE_MAX_ARCHIVE_BYTES:
        raise ValueError(
            f"Archive exceeds the {EXECUTE_CODE_MAX_ARCHIVE_BYTES} byte limit"
        )
    return data


def pack_sandbox_zip(chat_id: str, paths: list[str]) -> bytes:
    """Zip one or more sandbox files/directories (includes zarr internals)."""
    if not paths:
        raise ValueError("Provide at least one path to archive")
    resolved: list[tuple[str, Path]] = []
    total = 0
    seen: set[str] = set()
    for raw in paths:
        rel = normalize_sandbox_relpath(raw)
        if rel in seen:
            continue
        seen.add(rel)
        target = resolve_in_sandbox(chat_id, rel)
        if not target.exists():
            raise FileNotFoundError(f"Artifact not found: {rel}")
        total += sandbox_tree_size(target)
        if total > EXECUTE_CODE_MAX_ARCHIVE_BYTES:
            raise ValueError(
                f"Selected files exceed the {EXECUTE_CODE_MAX_ARCHIVE_BYTES} byte limit"
            )
        resolved.append((rel, target))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel, target in resolved:
            if target.is_file():
                zf.write(target, arcname=rel)
                continue
            for child in sorted(target.rglob("*")):
                if not child.is_file() or child.is_symlink():
                    continue
                arcname = Path(rel, child.relative_to(target)).as_posix()
                zf.write(child, arcname=arcname)
    data = buf.getvalue()
    if len(data) > EXECUTE_CODE_MAX_ARCHIVE_BYTES:
        raise ValueError(
            f"Archive exceeds the {EXECUTE_CODE_MAX_ARCHIVE_BYTES} byte limit"
        )
    return data


def extract_sandbox_archive(chat_id: str, data: bytes) -> list[str]:
    """Extract a gzip/tar archive into the chat sandbox. Returns written file paths."""
    if not data:
        raise ValueError("Empty archive")
    if len(data) > EXECUTE_CODE_MAX_ARCHIVE_BYTES:
        raise ValueError(
            f"Archive exceeds the {EXECUTE_CODE_MAX_ARCHIVE_BYTES} byte limit"
        )

    written: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar:
        for member in tar:
            if member.issym() or member.islnk():
                continue
            name = _safe_tar_member_name(member.name)
            dest = resolve_in_sandbox(chat_id, name)
            if member.isdir():
                make_sandbox_dir(dest, chat_sandbox(chat_id))
                continue
            if not member.isfile():
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            make_sandbox_dir(dest.parent, chat_sandbox(chat_id))
            payload = handle.read()
            payload = sanitize_output_artifact_bytes(name, payload)
            dest.write_bytes(payload)
            own_sandbox_path(dest)
            written.append(name)
    return written
