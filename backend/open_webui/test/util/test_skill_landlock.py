"""Tests for landlock_only and backend selection."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from open_webui.utils.skill_landlock import landlock_only_available, query_landlock_abi
from open_webui.utils.skill_sandlock import (
    confine_current_process,
    default_readable_paths,
    default_writable_paths,
    landlock_confinement_available,
    launcher_command,
    sandlock_usable,
    select_landlock_backend,
)


class LandlockBackendTest(unittest.TestCase):
    def test_backend_selection_prefers_sandlock_when_usable(self):
        if not landlock_confinement_available():
            self.skipTest("Landlock unavailable")
        backend = select_landlock_backend()
        self.assertIn(backend, ("sandlock", "landlock_only"))
        if sandlock_usable():
            self.assertEqual(backend, "sandlock")
        else:
            self.assertEqual(backend, "landlock_only")

    def test_landlock_only_confine_allows_echo_in_writable_dir(self):
        if not landlock_only_available():
            self.skipTest("landlock_only unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            cmd = launcher_command(
                writable=default_writable_paths(tmp, "/tmp"),
                readable=default_readable_paths(),
                cwd=tmp,
                argv=["/bin/echo", "landlock-ok"],
                backend="landlock_only",
            )
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("landlock-ok", proc.stdout)
            self.assertIn("confined via landlock_only", proc.stderr)

    def test_confine_current_process_returns_backend(self):
        if not landlock_confinement_available():
            self.skipTest("Landlock unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            # Fork a child to confine+exec because confine is irreversible.
            script = """
import os, sys
from open_webui.utils.skill_sandlock import confine_current_process, default_readable_paths, default_writable_paths
used = confine_current_process(
    writable=default_writable_paths(sys.argv[1], "/tmp"),
    readable=default_readable_paths(),
)
print(used, flush=True)
os.execvp("/bin/echo", ["/bin/echo", "ok"])
"""
            proc = subprocess.run(
                [sys.executable, "-c", script, tmp],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("ok", proc.stdout)
            backend = proc.stdout.strip().splitlines()[0]
            self.assertIn(backend, ("sandlock", "landlock_only"))
            if sandlock_usable():
                self.assertEqual(backend, "sandlock")
            else:
                self.assertEqual(backend, "landlock_only")


class LandlockAbiProbeTest(unittest.TestCase):
    def test_abi_probe_is_int(self):
        abi = query_landlock_abi()
        self.assertIsInstance(abi, int)


if __name__ == "__main__":
    unittest.main()
