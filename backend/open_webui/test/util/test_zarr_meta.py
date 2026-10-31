import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import xarray as xr
from fastapi import HTTPException

from open_webui.routers.artifacts import _render_view, zarr_meta

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_store(path: Path, zarr_format: int, consolidated: bool = False) -> None:
    ds = xr.Dataset(
        {
            "precip": (
                ("time", "latitude", "longitude"),
                np.arange(24, dtype="float32").reshape(2, 3, 4),
                {"units": "mm"},
            )
        },
        coords={
            "time": np.array(["2026-01-01", "2026-01-02"], dtype="datetime64[ns]"),
            "latitude": [0.0, 1.0, 2.0],
            "longitude": [30.0, 31.0, 32.0, 33.0],
        },
        attrs={"title": "demo"},
    )
    ds.to_zarr(path, zarr_format=zarr_format, consolidated=consolidated)


class ZarrMetaTest(unittest.IsolatedAsyncioTestCase):
    async def _meta(self, zarr_format: int, consolidated: bool) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-zarr"
            (artifacts / chat_id).mkdir(parents=True)
            store = artifacts / chat_id / "x.zarr"
            write_store(store, zarr_format, consolidated)
            np.testing.assert_array_equal(
                xr.open_zarr(store, consolidated=False)["precip"].values,
                np.arange(24, dtype="float32").reshape(2, 3, 4),
            )
            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.routers.artifacts._readable"),
            ):
                return await zarr_meta(chat_id, "x.zarr", user=MagicMock())

    def _assert_payload(self, meta: dict) -> None:
        self.assertEqual(
            meta["variables"],
            {
                "precip": {
                    "dims": ["time", "latitude", "longitude"],
                    "shape": [2, 3, 4],
                    "attrs": {"units": "mm"},
                }
            },
        )
        self.assertEqual(meta["dims"], {"time": 2, "latitude": 3, "longitude": 4})
        self.assertEqual(meta["attrs"], {"title": "demo"})

    async def test_reads_format_3_store(self):
        for consolidated in (False, True):
            with self.subTest(consolidated=consolidated):
                self._assert_payload(await self._meta(3, consolidated))

    async def test_reads_format_2_store(self):
        for consolidated in (False, True):
            with self.subTest(consolidated=consolidated):
                self._assert_payload(await self._meta(2, consolidated))

    async def test_rejects_plain_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = Path(tmp) / "artifacts"
            chat_id = "chat-zarr"
            (artifacts / chat_id / "plain").mkdir(parents=True)
            with (
                patch("open_webui.utils.artifacts.ARTIFACTS_DIR", artifacts),
                patch("open_webui.routers.artifacts._readable"),
            ):
                with self.assertRaises(HTTPException) as ctx:
                    await zarr_meta(chat_id, "plain", user=MagicMock())
            self.assertEqual(ctx.exception.status_code, 400)
            self.assertEqual(ctx.exception.detail, "Not a zarr store")


class RenderViewTest(unittest.TestCase):
    def _render(self, zarr_format: int) -> bytes:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "x.zarr"
            write_store(store, zarr_format)
            return _render_view(
                store, {"variable": "precip", "style": "heatmap", "index": {"time": 0}}
            )

    def test_renders_format_3_store(self):
        self.assertTrue(self._render(3).startswith(PNG_SIGNATURE))

    def test_renders_format_2_store(self):
        self.assertTrue(self._render(2).startswith(PNG_SIGNATURE))


if __name__ == "__main__":
    unittest.main()
