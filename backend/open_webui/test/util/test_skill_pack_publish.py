"""Skill pack publish skips unchanged JuiceFS files and serializes git ops."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from open_webui.models.skill_packs import SkillPackModel
from open_webui.utils.skills import (
    MANIFEST_NAME,
    SkillInstallBusyError,
    _copy_workers,
    _publish_working_tree,
    exclusive_git_op,
    parse_ls_remote,
    update_skill_pack,
)


class ParseLsRemoteTest(unittest.TestCase):
    def test_prefers_peeled_tag_commit(self):
        sha = parse_ls_remote(
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\trefs/tags/v1\n"
            "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\trefs/tags/v1^{}\n"
        )
        self.assertEqual(sha, "b" * 40)

    def test_uses_first_commit_when_unpeeled(self):
        sha = parse_ls_remote(
            "cccccccccccccccccccccccccccccccccccccccc\trefs/heads/main\n"
        )
        self.assertEqual(sha, "c" * 40)


class ExclusiveGitOpTest(unittest.TestCase):
    def test_second_caller_is_busy(self):
        with exclusive_git_op():
            with self.assertRaises(SkillInstallBusyError):
                with exclusive_git_op():
                    pass


class CopyWorkersTest(unittest.TestCase):
    def test_defaults_to_cpu_count_capped_at_32(self):
        with patch.dict("os.environ", {"SKILL_PACK_COPY_WORKERS": ""}):
            with patch("open_webui.utils.skills.os.cpu_count", return_value=8):
                self.assertEqual(_copy_workers(100), 8)
            with patch("open_webui.utils.skills.os.cpu_count", return_value=64):
                self.assertEqual(_copy_workers(100), 32)
            with patch("open_webui.utils.skills.os.cpu_count", return_value=None):
                self.assertEqual(_copy_workers(100), 1)


class PublishWorkingTreeTest(unittest.TestCase):
    def test_skips_unchanged_files_and_drops_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            dest = root / "dest"
            staging.mkdir()
            (staging / "keep.txt").write_text("same\n", encoding="utf-8")
            (staging / "change.txt").write_text("v1\n", encoding="utf-8")
            _publish_working_tree(staging, dest)

            keep_mtime = (dest / "keep.txt").stat().st_mtime_ns
            (staging / "change.txt").write_text("v2\n", encoding="utf-8")
            (staging / "stale.txt").write_text("gone\n", encoding="utf-8")
            _publish_working_tree(staging, dest)
            (dest / "stale.txt").write_text("old\n", encoding="utf-8")
            (staging / "stale.txt").unlink()
            _publish_working_tree(staging, dest)

            self.assertEqual((dest / "keep.txt").read_text(encoding="utf-8"), "same\n")
            self.assertEqual((dest / "change.txt").read_text(encoding="utf-8"), "v2\n")
            self.assertFalse((dest / "stale.txt").exists())
            self.assertEqual((dest / "keep.txt").stat().st_mtime_ns, keep_mtime)
            self.assertTrue((dest / MANIFEST_NAME).is_file())

    def test_strips_git_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staging = root / "staging"
            dest = root / "dest"
            staging.mkdir()
            (staging / "a.txt").write_text("a\n", encoding="utf-8")
            dest.mkdir()
            (dest / ".git").mkdir()
            (dest / "stale.txt").write_text("old\n", encoding="utf-8")
            _publish_working_tree(staging, dest)
            self.assertTrue((dest / "a.txt").is_file())
            self.assertFalse((dest / "stale.txt").exists())
            self.assertFalse((dest / ".git").exists())


class UpdateSkipCheckoutTest(unittest.TestCase):
    def test_skips_fetch_when_remote_sha_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "pack"
            dest.mkdir()
            (dest / "SKILL.md").write_text("x\n", encoding="utf-8")
            sha = "a" * 40
            pack = SkillPackModel(
                id="pack-1",
                user_id="user-1",
                name="demo@main",
                git_url="https://github.com/org/demo.git",
                git_ref="main",
                commit_sha=sha,
                local_path=str(dest),
                meta={"skills": []},
                access_control={},
                created_at=0,
                updated_at=0,
            )
            with (
                patch("open_webui.utils.skills.SkillPacks") as packs,
                patch(
                    "open_webui.utils.skills.resolve_remote_sha",
                    return_value=sha,
                ),
                patch("open_webui.utils.skills.checkout_ref") as checkout,
            ):
                packs.get_by_id.return_value = pack
                result = update_skill_pack("pack-1", {})
                checkout.assert_not_called()
                self.assertIs(result, pack)


if __name__ == "__main__":
    unittest.main()
