"""Serve precompressed Brotli siblings (app.js.br) when the client accepts br."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from starlette.staticfiles import StaticFiles

# These names are not fingerprinted, so a replaced file can take a day to show up.
STATIC_IMAGE_CACHE_CONTROL = "public, max-age=86400, immutable"
_STATIC_IMAGE_SUFFIXES = {".png", ".ico", ".svg", ".webp", ".gif", ".jpg", ".jpeg", ".avif"}
STATIC_AUDIO_CACHE_CONTROL = "public, max-age=86400"
_STATIC_AUDIO_SUFFIXES = {".mp3", ".ogg", ".wav"}

BROTLI_EXTENSIONS = {".js", ".mjs", ".css", ".html", ".json", ".svg", ".xml", ".txt"}
# Vite fingerprints these. A year is safe; the URL changes when the bytes change.
IMMUTABLE_CACHE_CONTROL = "public, max-age=31536000, immutable"
_IMMUTABLE_SUFFIXES = {".js", ".mjs", ".css"}

_TEXT_TYPES = {
	"application/javascript",
	"application/json",
	"application/xml",
	"image/svg+xml",
	"text/css",
	"text/html",
	"text/javascript",
	"text/plain",
	"text/xml",
}


def accepts_brotli(header: str | None) -> bool:
	if not header:
		return False
	for part in header.split(","):
		bits = [piece.strip() for piece in part.split(";") if piece.strip()]
		if not bits or bits[0].lower() != "br":
			continue
		quality = 1.0
		for param in bits[1:]:
			if param.lower().startswith("q="):
				try:
					quality = float(param.split("=", 1)[1])
				except ValueError:
					quality = 0
		return quality > 0
	return False


def immutable_cache_control(path: str) -> str | None:
	"""Long-lived cache for fingerprinted app JS and CSS only."""
	normalized = path.replace("\\", "/").lstrip("/")
	if not normalized.startswith("_app/immutable/"):
		return None
	if Path(normalized).suffix.lower() not in _IMMUTABLE_SUFFIXES:
		return None
	return IMMUTABLE_CACHE_CONTROL


def static_audio_cache_control(path: str) -> str | None:
	if Path(path).suffix.lower() in _STATIC_AUDIO_SUFFIXES:
		return STATIC_AUDIO_CACHE_CONTROL
	return None


def _apply_immutable_cache(response, path: str):
	value = immutable_cache_control(path) or static_audio_cache_control(path)
	if value:
		response.headers["cache-control"] = value
	return response


def _content_type(path: str) -> str:
	media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
	if media_type in _TEXT_TYPES or media_type.startswith("text/"):
		if "charset" not in media_type:
			return f"{media_type}; charset=utf-8"
	return media_type


class PrecompressedStaticFiles(StaticFiles):
	async def get_response(self, path: str, scope):
		brotli = self._brotli_response(path, scope)
		if brotli is not None:
			response = await brotli
		else:
			response = await super().get_response(path, scope)
		return _apply_immutable_cache(response, path)

	def _brotli_response(self, path: str, scope):
		headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
		if not accepts_brotli(headers.get("accept-encoding")):
			return None
		suffix = Path(path).suffix.lower()
		if suffix not in BROTLI_EXTENSIONS:
			return None
		directory = Path(self.directory).resolve()
		candidate = (directory / f"{path}.br").resolve()
		try:
			candidate.relative_to(directory)
		except ValueError:
			return None
		if not candidate.is_file():
			return None

		async def respond():
			response = await super(PrecompressedStaticFiles, self).get_response(f"{path}.br", scope)
			response.headers["content-type"] = _content_type(path)
			response.headers["content-encoding"] = "br"
			vary = response.headers.get("vary")
			response.headers["vary"] = "Accept-Encoding" if not vary else f"{vary}, Accept-Encoding"
			return response

		return respond()


def static_image_cache_control(path: str) -> str | None:
	if Path(path).suffix.lower() in _STATIC_IMAGE_SUFFIXES:
		return STATIC_IMAGE_CACHE_CONTROL
	return None


class ImageCachedStaticFiles(StaticFiles):
	"""Cache logo, favicon, and other /static images. Scripts stay revalidated."""

	async def get_response(self, path: str, scope):
		response = await super().get_response(path, scope)
		value = static_image_cache_control(path)
		if value:
			response.headers["cache-control"] = value
		return response
