"""Pack + tools are staged on one session and committed once."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from open_webui.models.skill_packs import SkillPackModel
from open_webui.utils.skills import (
    _sync_pack_tools,
    tool_id_for_skill,
)


def _write_skill(root: Path, name: str) -> None:
    skill = root / name
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        f"---\nname: {name}\n---\n# {name}\n",
        encoding="utf-8",
    )
    scripts = skill / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text("print(1)\n", encoding="utf-8")


class ToolIdForSkillTest(unittest.TestCase):
    def test_skips_ids_already_in_the_occupied_set(self):
        self.assertEqual(tool_id_for_skill("plot", "pack", set()), "skill_plot")
        self.assertEqual(
            tool_id_for_skill("plot", "my-pack", {"skill_plot"}),
            "skill_my-pack_plot",
        )


class SyncPackToolsTransactionTest(unittest.TestCase):
    def test_stages_new_tools_with_add_all_and_does_not_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_skill(root, "alpha")
            _write_skill(root, "beta")
            pack = SkillPackModel(
                id="pack-1",
                user_id="user-1",
                name="demo@main",
                git_url="https://github.com/org/demo.git",
                git_ref="main",
                commit_sha="abc",
                local_path=str(root),
                meta={"skills": []},
                access_control=None,
                created_at=0,
                updated_at=0,
            )
            db = MagicMock()
            pack_row = MagicMock()
            pack_row.id = pack.id
            pack_row.user_id = pack.user_id
            pack_row.name = pack.name
            pack_row.git_url = pack.git_url
            pack_row.git_ref = pack.git_ref
            pack_row.commit_sha = pack.commit_sha
            pack_row.local_path = pack.local_path
            pack_row.meta = {}
            pack_row.access_control = None
            pack_row.created_at = 0
            pack_row.updated_at = 0
            db.get.return_value = pack_row
            db.query.return_value.filter.return_value.all.return_value = []

            with (
                patch(
                    "open_webui.utils.skills.load_tool_module_by_id",
                    return_value=(MagicMock(), {}),
                ),
                patch("open_webui.utils.skills.get_tool_specs", return_value=[]),
            ):
                synced, modules, stale = _sync_pack_tools(db, pack, user_id="user-1")

            db.commit.assert_not_called()
            db.add_all.assert_called_once()
            added = db.add_all.call_args[0][0]
            self.assertEqual(len(added), 2)
            self.assertEqual(stale, set())
            self.assertEqual(len(modules), 2)
            self.assertEqual(len(synced.skills), 2)
            self.assertIn("skills", pack_row.meta)
            db.flush.assert_called_once()
