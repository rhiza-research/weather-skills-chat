import tempfile
import unittest
from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from open_webui.utils.precompressed_static import (
	IMMUTABLE_CACHE_CONTROL,
	STATIC_AUDIO_CACHE_CONTROL,
	STATIC_IMAGE_CACHE_CONTROL,
	ImageCachedStaticFiles,
	PrecompressedStaticFiles,
	accepts_brotli,
	immutable_cache_control,
)


class AcceptsBrotliTest(unittest.TestCase):
	def test_quality(self):
		self.assertTrue(accepts_brotli("gzip, deflate, br"))
		self.assertFalse(accepts_brotli("gzip"))
		self.assertFalse(accepts_brotli("br;q=0, gzip"))
		self.assertFalse(accepts_brotli(None))


class PrecompressedStaticFilesTest(unittest.TestCase):
	def test_serves_brotli_sibling_or_raw_file(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			original = b"const answer = 42;\n" * 40
			(root / "app.js").write_bytes(original)
			(root / "app.js.br").write_bytes(b"compressed-body")
			client = TestClient(
				Starlette(
					routes=[Mount("/", PrecompressedStaticFiles(directory=root, html=True))]
				)
			)

			brotli = client.get("/app.js", headers={"Accept-Encoding": "gzip, br"})
			self.assertEqual(brotli.status_code, 200)
			self.assertEqual(brotli.headers["content-encoding"], "br")
			self.assertIn("javascript", brotli.headers["content-type"])
			self.assertEqual(brotli.headers["vary"], "Accept-Encoding")
			self.assertEqual(brotli.content, b"compressed-body")

			plain = client.get("/app.js", headers={"Accept-Encoding": "gzip"})
			self.assertEqual(plain.status_code, 200)
			self.assertNotIn("content-encoding", plain.headers)
			self.assertEqual(plain.content, original)
			self.assertNotIn("cache-control", plain.headers)

	def test_immutable_js_and_css_are_cached_for_a_year(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			js = root / "_app" / "immutable" / "chunks"
			css = root / "_app" / "immutable" / "assets"
			js.mkdir(parents=True)
			css.mkdir(parents=True)
			(js / "app.js").write_bytes(b"const answer = 42;\n" * 40)
			(js / "app.js.br").write_bytes(b"compressed-body")
			(css / "app.css").write_bytes(b"body{color:black}\n" * 20)
			(root / "index.html").write_text("<!doctype html><title>x</title>")
			client = TestClient(
				Starlette(
					routes=[Mount("/", PrecompressedStaticFiles(directory=root, html=True))]
				)
			)

			script = client.get(
				"/_app/immutable/chunks/app.js", headers={"Accept-Encoding": "br"}
			)
			self.assertEqual(script.headers["cache-control"], IMMUTABLE_CACHE_CONTROL)
			self.assertEqual(script.headers["content-encoding"], "br")

			sheet = client.get("/_app/immutable/assets/app.css")
			self.assertEqual(sheet.headers["cache-control"], IMMUTABLE_CACHE_CONTROL)

			page = client.get("/index.html")
			self.assertEqual(page.status_code, 200)
			self.assertNotIn("cache-control", page.headers)

			(root / "audio").mkdir()
			(root / "audio" / "notification.mp3").write_bytes(b"ID3" + b"\x00" * 32)
			sound = client.get("/audio/notification.mp3")
			self.assertEqual(sound.status_code, 200)
			self.assertEqual(sound.headers["cache-control"], STATIC_AUDIO_CACHE_CONTROL)

		self.assertIsNone(immutable_cache_control("assets/fonts/Archivo-Variable.woff2"))
		self.assertIsNone(immutable_cache_control("_app/immutable/nodes/app.html"))


class ImageCachedStaticFilesTest(unittest.TestCase):
	def test_images_are_cached_and_scripts_are_not(self):
		with tempfile.TemporaryDirectory() as tmp:
			root = Path(tmp)
			(root / "favicon.png").write_bytes(b"\x89PNG\r\n")
			(root / "loader.js").write_text("console.log(1)\n")
			client = TestClient(
				Starlette(routes=[Mount("/static", ImageCachedStaticFiles(directory=root))])
			)

			icon = client.get("/static/favicon.png")
			self.assertEqual(icon.headers["cache-control"], STATIC_IMAGE_CACHE_CONTROL)

			script = client.get("/static/loader.js")
			self.assertNotIn("cache-control", script.headers)
