"""Canceling run_skill must kill the OS process tree (chat Stop)."""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path

from open_webui.utils.skill_runtime import run_skill


class RunSkillCancelTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_kills_skill_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp)
            scripts = skill / "scripts"
            scripts.mkdir()
            (scripts / "sleep.py").write_text(
                "# /// script\n"
                "# requires-python = \">=3.11\"\n"
                "# dependencies = []\n"
                "# ///\n"
                "import os, pathlib, time\n"
                "pid_path = pathlib.Path(os.environ['WEATHER_INTERMEDIATE_DIR']) / 'pid'\n"
                "pid_path.write_text(str(os.getpid()))\n"
                "time.sleep(120)\n",
                encoding="utf-8",
            )

            task = asyncio.create_task(
                run_skill(
                    skill,
                    script="sleep.py",
                    __metadata__={},
                    timeout=600,
                )
            )

            pid_path = skill / ".work" / "intermediate_results" / "pid"
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if pid_path.is_file() and pid_path.read_text().strip().isdigit():
                    break
                if task.done():
                    break
                await asyncio.sleep(0.1)

            self.assertFalse(task.done(), "skill exited before cancel")
            self.assertTrue(pid_path.is_file(), "skill never wrote pid file")
            child_pid = int(pid_path.read_text().strip())

            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

            # Process group kill should reap the script child.
            gone_deadline = time.monotonic() + 5
            while time.monotonic() < gone_deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                await asyncio.sleep(0.05)
            else:
                self.fail(f"skill child pid {child_pid} still alive after cancel")


if __name__ == "__main__":
    unittest.main()
