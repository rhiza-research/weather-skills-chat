import io
import json
import shutil
import tarfile
import zipfile
from pathlib import Path
from open_webui.env import ARTIFACTS_DIR

ZARR_MARKERS = (".zgroup", ".zarray", "zarr.json")
INTERMEDIATE_RESULTS_DIRNAME = "intermediate_results"


def chat_sandbox(chat_id: str) -> Path:
    root = (ARTIFACTS_DIR / chat_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / INTERMEDIATE_RESULTS_DIRNAME).mkdir(parents=True, exist_ok=True)
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

    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()

    if src.is_dir():
        shutil.copytree(src, dest)
        kind = "directory"
    else:
        shutil.copy2(src, dest)
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
    target.mkdir(parents=True, exist_ok=True)
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


def list_artifacts(chat_id: str) -> list[dict]:
    root = chat_sandbox(chat_id)
    entries = []

    def walk(directory: Path):
        for path in sorted(directory.iterdir()):
            # Hide dotfiles/dirs (uv cache, HOME scratch under Landlock, etc.)
            if path.name.startswith("."):
                continue
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
            if kind == "image" and path.suffix.lower() == ".png":
                prov = provenance_for_png(path)
                if prov:
                    # crumbs kept for compact labels; branches carry full args.
                    item["provenance"] = prov.get("crumbs") or []
                    item["provenance_detail"] = prov
            elif kind == "zarr":
                prov = provenance_for_zarr(path)
                if prov:
                    item["provenance"] = prov.get("crumbs") or []
                    item["provenance_detail"] = prov
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
        # Ensure the scratch folder exists even if the source predated it.
        (dest / INTERMEDIATE_RESULTS_DIRNAME).mkdir(parents=True, exist_ok=True)


def delete_sandbox(chat_id: str) -> None:
    root = (ARTIFACTS_DIR / chat_id).resolve()
    if root.exists() and ARTIFACTS_DIR in root.parents:
        shutil.rmtree(root, ignore_errors=True)


def write_bytes(chat_id: str, relpath: str, data: bytes) -> Path:
    target = resolve_in_sandbox(chat_id, relpath)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


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
                dest.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            handle = tar.extractfile(member)
            if handle is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            payload = handle.read()
            payload = sanitize_output_artifact_bytes(name, payload)
            dest.write_bytes(payload)
            written.append(name)
    return written


def write_json(chat_id: str, relpath: str, payload: dict) -> Path:
    target = resolve_in_sandbox(chat_id, relpath)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2))
    return target
