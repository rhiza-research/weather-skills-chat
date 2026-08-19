"""Serve vendored Pyodide wheels, and proxy lockfile packages from jsDelivr.

Open WebUI's SPA fallback returns index.html for missing paths. Pyodide then
treats that 200 HTML as a wheel, micropip.install reports success, and import
fails. Dedicated /pyodide handling 404s (or proxies) instead.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import aiohttp
from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, Response

log = logging.getLogger(__name__)

# SPA routes have no extension (or .html). Anything else missing is a real 404.
SPA_NO_FALLBACK_SUFFIXES = (
    ".js",
    ".mjs",
    ".cjs",
    ".css",
    ".map",
    ".json",
    ".txt",
    ".whl",
    ".wasm",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".data",
    ".so",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)

_PYODIDE_PROXY_SUFFIXES = (".whl", ".tar", ".zip", ".data")


def should_spa_fallback(path: str) -> bool:
    lowered = (path or "").split("?", 1)[0].lower()
    return not lowered.endswith(SPA_NO_FALLBACK_SUFFIXES)


def _safe_filename(path: str) -> str | None:
    cleaned = (path or "").replace("\\", "/").lstrip("/")
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned:
        return None
    return cleaned


def load_pyodide_lock(lock_path: Path, pyodide_dir: Path | None = None) -> tuple[str, set[str]]:
    data = json.loads(lock_path.read_text())
    info = data.get("info") or {}
    version = info.get("version")
    if not version and pyodide_dir is not None:
        pkg_json = Path(pyodide_dir) / "package.json"
        if pkg_json.is_file():
            try:
                version = json.loads(pkg_json.read_text()).get("version")
            except Exception:
                version = None
    version = str(version or "0.27.3")
    files = {
        pkg["file_name"]
        for pkg in (data.get("packages") or {}).values()
        if isinstance(pkg, dict) and pkg.get("file_name")
    }
    return version, files


class PyodidePackageStaticFiles(StaticFiles):
    """Serve local Pyodide files; proxy missing lockfile wheels from jsDelivr."""

    def __init__(
        self,
        directory: str | Path,
        cache_dir: str | Path,
        lock_path: str | Path | None = None,
        **kwargs,
    ):
        super().__init__(directory=directory, **kwargs)
        self.directory = Path(directory)
        self.cache_dir = Path(cache_dir)
        lock = Path(lock_path) if lock_path else self.directory / "pyodide-lock.json"
        try:
            self.pyodide_version, self.lockfile_names = load_pyodide_lock(
                lock, self.directory
            )
        except FileNotFoundError:
            log.warning("Pyodide lock file missing at %s", lock)
            self.pyodide_version, self.lockfile_names = "314.0.5", set()
        except Exception:
            log.exception("Failed to read Pyodide lock file %s", lock)
            self.pyodide_version, self.lockfile_names = "314.0.5", set()

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except (HTTPException, StarletteHTTPException) as ex:
            if ex.status_code != 404:
                raise
            proxied = await self._proxy_lockfile_package(path)
            if proxied is None:
                raise
            return proxied

    async def _proxy_lockfile_package(self, path: str) -> Response | None:
        filename = _safe_filename(path)
        if filename is None:
            return None
        if filename not in self.lockfile_names:
            return None
        if not filename.lower().endswith(_PYODIDE_PROXY_SUFFIXES):
            return None

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached = self.cache_dir / filename
        if cached.is_file() and cached.stat().st_size > 0:
            return FileResponse(cached)

        url = (
            f"https://cdn.jsdelivr.net/pyodide/v{self.pyodide_version}/full/{filename}"
        )
        timeout = aiohttp.ClientTimeout(total=120)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        log.warning(
                            "Pyodide CDN miss %s -> %s", url, resp.status
                        )
                        return None
                    data = await resp.read()
        except Exception:
            log.exception("Failed to fetch Pyodide package %s", url)
            return None

        try:
            cached.write_bytes(data)
            return FileResponse(cached)
        except Exception:
            log.exception("Failed to cache Pyodide package %s", filename)
            return Response(content=data, media_type="application/octet-stream")
