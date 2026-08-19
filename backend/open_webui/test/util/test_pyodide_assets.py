from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from open_webui.utils.pyodide_assets import (
    _safe_filename,
    load_pyodide_lock,
    should_spa_fallback,
)


class SpaFallbackTest(unittest.TestCase):
    def test_client_routes_still_fall_back(self):
        self.assertTrue(should_spa_fallback("c/abc"))
        self.assertTrue(should_spa_fallback("admin/settings"))
        self.assertTrue(should_spa_fallback("index.html"))

    def test_missing_wheels_do_not_fall_back(self):
        self.assertFalse(should_spa_fallback("pyodide/xarray-2024.11.0-py3-none-any.whl"))
        self.assertFalse(should_spa_fallback("app.js"))
        self.assertFalse(should_spa_fallback("pyodide/pyodide.asm.wasm"))


class PyodideLockTest(unittest.TestCase):
    def test_reads_version_from_package_json_when_lock_has_no_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = root / "pyodide-lock.json"
            lock.write_text(
                json.dumps(
                    {
                        "info": {"python": "3.14.2", "abi_version": "2026_0"},
                        "packages": {
                            "xarray": {
                                "file_name": "xarray-2026.2.0-py3-none-any.whl"
                            }
                        },
                    }
                )
            )
            (root / "package.json").write_text(json.dumps({"version": "314.0.5"}))
            version, names = load_pyodide_lock(lock, root)
            self.assertEqual(version, "314.0.5")
            self.assertIn("xarray-2026.2.0-py3-none-any.whl", names)

    def test_reads_version_and_file_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "pyodide-lock.json"
            lock.write_text(
                json.dumps(
                    {
                        "info": {"version": "0.27.3"},
                        "packages": {
                            "xarray": {
                                "file_name": "xarray-2024.11.0-py3-none-any.whl"
                            }
                        },
                    }
                )
            )
            version, names = load_pyodide_lock(lock)
            self.assertEqual(version, "0.27.3")
            self.assertIn("xarray-2024.11.0-py3-none-any.whl", names)

    def test_rejects_nested_paths(self):
        self.assertIsNone(_safe_filename("../xarray.whl"))
        self.assertIsNone(_safe_filename("a/b.whl"))
        self.assertEqual(_safe_filename("xarray-1.whl"), "xarray-1.whl")


if __name__ == "__main__":
    unittest.main()
