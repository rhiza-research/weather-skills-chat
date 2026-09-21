"""Payload-prep tool catalog: one in-memory pass, no per-id DB reads."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from open_webui.models.tools import ToolCatalogModel, ToolMeta
from open_webui.utils.tools import accessible_skill_records, get_tools


def _skill(tool_id: str, name: str, version: str, user_id: str = "alice") -> ToolCatalogModel:
    return ToolCatalogModel(
        id=tool_id,
        user_id=user_id,
        name=name,
        specs=[
            {
                "name": name,
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        meta=ToolMeta(
            description=name,
            manifest={
                "kind": "skill",
                "skill_name": name,
                "version": version,
                "enabled": True,
            },
        ),
        access_control=None,
        valves={},
        updated_at=1,
        created_at=1,
    )


class AccessibleSkillRecordsCatalogTest(unittest.TestCase):
    def test_uses_provided_catalog_without_db(self):
        user = SimpleNamespace(id="alice", role="user")
        catalog = [_skill("skill_plot__v1", "plot", "0.1.0")]
        with patch("open_webui.utils.tools.Tools.get_tool_catalog") as mock_catalog, patch(
            "open_webui.utils.tools.Tools.get_tools"
        ) as mock_get_tools, patch(
            "open_webui.utils.tools.Tools.get_tool_by_id"
        ) as mock_get:
            records = accessible_skill_records(user, catalog)
        mock_catalog.assert_not_called()
        mock_get_tools.assert_not_called()
        mock_get.assert_not_called()
        self.assertEqual([r["id"] for r in records], ["skill_plot__v1"])


class GetToolsCatalogTest(unittest.TestCase):
    def test_resolves_from_catalog_without_per_id_reads(self):
        user = SimpleNamespace(id="alice", role="user", settings=None)
        catalog = [_skill("skill_plot__v1", "plot", "0.1.0")]
        module = SimpleNamespace()

        def plot():
            """Plot something."""
            return None

        module.plot = plot
        request = MagicMock()
        request.app.state.TOOLS = {"skill_plot__v1": module}

        with patch("open_webui.utils.tools.Tools.get_tool_catalog") as mock_catalog, patch(
            "open_webui.utils.tools.Tools.get_tool_by_id"
        ) as mock_get, patch(
            "open_webui.utils.tools.load_tool_module_by_id"
        ) as mock_load:
            tools = get_tools(
                request,
                ["skill_plot__v1"],
                user,
                {"__user__": {"id": "alice"}},
                catalog=catalog,
            )

        mock_catalog.assert_not_called()
        mock_get.assert_not_called()
        mock_load.assert_not_called()
        self.assertIn("plot", tools)
        self.assertEqual(tools["plot"]["tool_id"], "skill_plot__v1")


if __name__ == "__main__":
    unittest.main()
