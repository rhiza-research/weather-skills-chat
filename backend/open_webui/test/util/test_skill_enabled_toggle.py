"""Per-skill global enabled flag on skill packs."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from open_webui.models.skill_packs import SkillPackModel
from open_webui.utils.skills import set_skill_enabled


class SkillEnabledToggleTest(unittest.TestCase):
    def test_set_skill_enabled_updates_pack_and_tool_manifest(self):
        pack = SkillPackModel(
            id="pack-1",
            user_id="user-1",
            name="demo@main",
            git_url="https://github.com/org/demo.git",
            git_ref="main",
            commit_sha="abc",
            local_path="/tmp/demo",
            meta={
                "skills": [
                    {
                        "name": "plot",
                        "tool_id": "tool_plot",
                        "enabled": True,
                    }
                ]
            },
            access_control={},
            created_at=0,
            updated_at=0,
        )
        updated = pack.model_copy(
            update={
                "meta": {
                    "skills": [
                        {
                            "name": "plot",
                            "tool_id": "tool_plot",
                            "enabled": False,
                        }
                    ]
                }
            }
        )
        tool = MagicMock()
        tool.meta = MagicMock()
        tool.meta.model_dump.return_value = {
            "description": "d",
            "manifest": {"kind": "skill", "pack_id": "pack-1", "enabled": True},
        }

        with (
            patch("open_webui.utils.skills.SkillPacks") as packs,
            patch("open_webui.utils.skills.Tools") as tools,
        ):
            packs.get_by_id.return_value = pack
            packs.update.return_value = updated
            tools.get_tool_by_id.return_value = tool

            result = set_skill_enabled("pack-1", "tool_plot", False)

            packs.update.assert_called_once()
            args = packs.update.call_args[0]
            self.assertEqual(args[0], "pack-1")
            self.assertFalse(args[1]["meta"]["skills"][0]["enabled"])
            tools.update_tool_by_id.assert_called_once()
            tool_update = tools.update_tool_by_id.call_args[0][1]
            self.assertFalse(tool_update["meta"]["manifest"]["enabled"])
            self.assertIs(result, updated)


if __name__ == "__main__":
    unittest.main()
