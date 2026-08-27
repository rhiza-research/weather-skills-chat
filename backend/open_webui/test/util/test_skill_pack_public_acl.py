"""Public skill-pack ACL must stay None (not coerced to private {})."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from open_webui.models.skill_packs import SkillPackModel
from open_webui.utils.skills import _upsert_skill_tool, set_pack_access_control


class PublicAclPropagationTest(unittest.TestCase):
    def test_upsert_passes_none_access_control_for_new_tool(self):
        pack = SkillPackModel(
            id="pack-1",
            user_id="user-1",
            name="demo@main",
            git_url="https://github.com/org/demo.git",
            git_ref="main",
            commit_sha="abc",
            local_path="/tmp/demo",
            meta={},
            access_control=None,
            created_at=0,
            updated_at=0,
        )
        skill = MagicMock()
        skill.name = "demo-skill"
        skill.version = "1.0.0"
        skill.description = "desc"
        skill.usage = ""
        skill.skill_dir = "/tmp/demo/demo-skill"
        skill.relative_path = "demo-skill"
        skill.scripts = ["scripts/run.py"]

        with (
            patch("open_webui.utils.skills.generate_tool_content", return_value="# tool"),
            patch("open_webui.utils.skills.replace_imports", side_effect=lambda x: x),
            patch(
                "open_webui.utils.skills.load_tool_module_by_id",
                return_value=(MagicMock(), {}),
            ),
            patch("open_webui.utils.skills.get_tool_specs", return_value=[]),
            patch("open_webui.utils.skills.Tools") as tools,
        ):
            tools.get_tool_by_id.return_value = None
            _upsert_skill_tool(
                request_app_tools={},
                user_id="user-1",
                pack=pack,
                skill=skill,
                tool_id="tool_demo",
                preserve_access_control=None,
            )
            form = tools.insert_new_tool.call_args[0][1]
            self.assertIsNone(form.access_control)

    def test_upsert_updates_existing_tool_to_public_none(self):
        pack = SkillPackModel(
            id="pack-1",
            user_id="user-1",
            name="demo@main",
            git_url="https://github.com/org/demo.git",
            git_ref="main",
            commit_sha="abc",
            local_path="/tmp/demo",
            meta={},
            access_control=None,
            created_at=0,
            updated_at=0,
        )
        skill = MagicMock()
        skill.name = "demo-skill"
        skill.version = "1.0.0"
        skill.description = "desc"
        skill.usage = ""
        skill.skill_dir = "/tmp/demo/demo-skill"
        skill.relative_path = "demo-skill"
        skill.scripts = ["scripts/run.py"]

        existing = MagicMock()
        existing.access_control = {}

        with (
            patch("open_webui.utils.skills.generate_tool_content", return_value="# tool"),
            patch("open_webui.utils.skills.replace_imports", side_effect=lambda x: x),
            patch(
                "open_webui.utils.skills.load_tool_module_by_id",
                return_value=(MagicMock(), {}),
            ),
            patch("open_webui.utils.skills.get_tool_specs", return_value=[]),
            patch("open_webui.utils.skills.Tools") as tools,
        ):
            tools.get_tool_by_id.return_value = existing
            _upsert_skill_tool(
                request_app_tools={},
                user_id="user-1",
                pack=pack,
                skill=skill,
                tool_id="tool_demo",
                preserve_access_control=None,
            )
            updated = tools.update_tool_by_id.call_args[0][1]
            self.assertIsNone(updated["access_control"])

    def test_set_pack_access_control_writes_none(self):
        pack = SkillPackModel(
            id="pack-1",
            user_id="user-1",
            name="demo@main",
            git_url="https://github.com/org/demo.git",
            git_ref="main",
            commit_sha="abc",
            local_path="/tmp/demo",
            meta={"skills": [{"tool_id": "tool_a"}]},
            access_control={},
            created_at=0,
            updated_at=0,
        )
        updated = pack.model_copy(update={"access_control": None})
        tool = MagicMock()
        tool.access_control = {}
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [tool]

        with (
            patch("open_webui.utils.skills.SkillPacks") as packs,
            patch("open_webui.internal.db.get_db") as get_db,
            patch("open_webui.models.tools.Tool"),
        ):
            packs.get_by_id.return_value = pack
            packs.update.return_value = updated
            get_db.return_value.__enter__.return_value = db

            result = set_pack_access_control("pack-1", None)

            packs.update.assert_called_once_with(
                "pack-1", {"access_control": None}
            )
            self.assertIsNone(result.access_control)
            self.assertIsNone(tool.access_control)
            db.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
