"""checkout_ref publishes a shallow working tree without .git."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from open_webui.utils.skills import checkout_ref


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "user.email=test@example.com", "-c", "user.name=test", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


class CheckoutRefTest(unittest.TestCase):
    def test_shallow_publish_omits_git_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            dest = root / "dest"
            src.mkdir()
            (src / "README.md").write_text("hello\n", encoding="utf-8")
            skills = src / "skills" / "demo"
            skills.mkdir(parents=True)
            (skills / "SKILL.md").write_text("---\nname: demo\n---\n", encoding="utf-8")

            _git(["init"], cwd=src)
            _git(["add", "."], cwd=src)
            _git(["commit", "-m", "init"], cwd=src)
            _git(["branch", "-M", "main"], cwd=src)

            sha = checkout_ref(dest, str(src), "main")

            self.assertTrue(sha)
            self.assertTrue((dest / "README.md").is_file())
            self.assertTrue((dest / "skills" / "demo" / "SKILL.md").is_file())
            self.assertFalse((dest / ".git").exists())

    def test_replace_existing_dest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            dest = root / "dest"
            src.mkdir()
            (src / "a.txt").write_text("a\n", encoding="utf-8")
            _git(["init"], cwd=src)
            _git(["add", "."], cwd=src)
            _git(["commit", "-m", "init"], cwd=src)
            _git(["branch", "-M", "main"], cwd=src)

            dest.mkdir()
            (dest / "stale.txt").write_text("old\n", encoding="utf-8")
            (dest / ".git").mkdir()

            checkout_ref(dest, str(src), "main")

            self.assertTrue((dest / "a.txt").is_file())
            self.assertFalse((dest / "stale.txt").exists())
            self.assertFalse((dest / ".git").exists())


if __name__ == "__main__":
    unittest.main()
