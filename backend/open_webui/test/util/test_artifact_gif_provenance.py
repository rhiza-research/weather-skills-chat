"""GIF artifacts carry their provenance chain in the GIF comment block."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from open_webui.utils.artifacts import artifact_provenance, list_artifacts

CHAIN = [
    {"skill": "dynamical-fetch", "version": "0.0.4", "args": {"dataset": "gfs"}, "input": None},
    {"skill": "plot", "version": "1.0.0", "args": {"animate": True}, "input": "precip.zarr"},
]


def _write_gif(path: Path, comment: bytes | None = None) -> None:
    frames = [Image.new("RGB", (4, 4), c) for c in ("red", "blue")]
    extra = {"comment": comment} if comment is not None else {}
    # Saved the way weather-skills-core stamps a figure.
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0, **extra)


class GifProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.artifacts = Path(self.tmp.name) / "artifacts"
        self.root = self.artifacts / "chat-g"
        (self.root / "plots").mkdir(parents=True)
        self.patch = patch("open_webui.utils.artifacts.ARTIFACTS_DIR", self.artifacts)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def _listing(self):
        return {item["path"]: item for item in list_artifacts("chat-g", provenance_depth=1)}

    def test_stamped_gif_is_listed_with_its_chain(self):
        _write_gif(self.root / "anim.gif", json.dumps(CHAIN).encode("utf-8"))
        item = self._listing()["anim.gif"]
        self.assertEqual(item["kind"], "image")
        self.assertEqual(item["provenance"], ["dynamical-fetch", "plot"])
        self.assertEqual(item["provenance_branches"], [{"label": None, "crumbs": ["dynamical-fetch", "plot"]}])

    def test_nested_gif_is_read_on_request(self):
        _write_gif(self.root / "plots" / "anim.gif", json.dumps(CHAIN).encode("utf-8"))
        self.assertNotIn("provenance", self._listing()["plots/anim.gif"])
        steps = artifact_provenance("chat-g", "plots/anim.gif")["branches"][0]["steps"]
        self.assertEqual([s["skill"] for s in steps], ["dynamical-fetch", "plot"])
        self.assertEqual(steps[1]["args"], {"animate": True})

    def test_gif_without_a_comment_has_none(self):
        _write_gif(self.root / "plain.gif")
        self.assertNotIn("provenance", self._listing()["plain.gif"])
        self.assertIsNone(artifact_provenance("chat-g", "plain.gif"))

    def test_gif_whose_comment_is_not_a_chain_has_none(self):
        _write_gif(self.root / "note.gif", b"made in GIMP")
        self.assertNotIn("provenance", self._listing()["note.gif"])
        self.assertIsNone(artifact_provenance("chat-g", "note.gif"))

    def test_file_named_gif_that_is_not_one_has_none(self):
        (self.root / "fake.gif").write_bytes(b"not a gif")
        self.assertIsNone(artifact_provenance("chat-g", "fake.gif"))
