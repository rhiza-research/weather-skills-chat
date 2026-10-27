"""Automations keep skill names and run the newest copy of each in their org."""

from __future__ import annotations

import importlib.util
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from open_webui.models.automations import (
    AutomationForm,
    Automations,
    AutomationUpdateForm,
)
from open_webui.models.tools import ToolCatalogModel, ToolMeta
from open_webui.utils import automation_runner
from open_webui.utils.skill_version import tool_ids_with_skill_names


def _skill(tool_id: str, name: str, version: str = "1.0.0") -> ToolCatalogModel:
    return ToolCatalogModel(
        id=tool_id,
        user_id="alice",
        name=name,
        specs=[],
        meta=ToolMeta(
            description=name,
            manifest={"kind": "skill", "skill_name": name, "version": version},
        ),
        access_control=None,
        valves={},
        updated_at=1,
        created_at=1,
    )


def _tool(tool_id: str) -> ToolCatalogModel:
    return ToolCatalogModel(
        id=tool_id,
        user_id="alice",
        name=tool_id,
        specs=[],
        meta=ToolMeta(description=tool_id, manifest={}),
        access_control=None,
        valves={},
        updated_at=1,
        created_at=1,
    )


def _record(tool_id: str, name: str, version: str) -> dict:
    return {"id": tool_id, "skill_name": name, "version": version, "enabled": True}


class ToolIdsWithSkillNamesTest(unittest.TestCase):
    def test_skill_ids_become_names_and_other_tools_stay_ids(self):
        catalog = [_skill("skill_x__plot", "plot"), _tool("my_function_tool")]
        self.assertEqual(
            tool_ids_with_skill_names(
                ["skill_x__plot", "my_function_tool", "server:0", "skill_x__plot"],
                catalog,
            ),
            ["plot", "my_function_tool", "server:0"],
        )

    def test_names_are_kept(self):
        # The edit form sends back the list it loaded, names included.
        catalog = [_skill("skill_x__plot", "plot")]
        self.assertEqual(tool_ids_with_skill_names(["plot"], catalog), ["plot"])


class AutomationRunPassesNamesTest(unittest.TestCase):
    def test_saved_names_go_to_the_request_unchanged(self):
        # Payload prep resolves them, as it does a chat's selection.
        automation = SimpleNamespace(
            organization_id="org-rhiza", tool_ids=["smap-fetch", "plot", "server:0"]
        )
        with patch(
            "open_webui.utils.tools.accessible_skill_records"
        ) as mock_records:
            ids = automation_runner._resolve_tool_ids(
                automation, None, SimpleNamespace(id="gen", role="user")
            )
        self.assertEqual(ids, ["smap-fetch", "plot", "server:0"])
        mock_records.assert_not_called()

    def test_no_selection_still_offers_every_usable_tool(self):
        automation = SimpleNamespace(organization_id="org-rhiza", tool_ids=None)
        with patch.object(
            automation_runner, "_accessible_tool_ids", return_value=["skill_plot"]
        ) as mock_all:
            ids = automation_runner._resolve_tool_ids(
                automation, None, SimpleNamespace(id="gen", role="user")
            )
        self.assertEqual(ids, ["skill_plot"])
        mock_all.assert_called_once()


class PayloadPrepResolvesNamesTest(unittest.TestCase):
    def test_names_resolve_once_to_the_newest_copy_in_the_request_org(self):
        # The pack was reinstalled: the IDs saved before no longer exist.
        from open_webui.utils import middleware

        records = [
            _record("skill_weather-skills__main__c3845fd2_smap_fetch", "smap-fetch", "0.4.0"),
            _record("skill_weather-skills-plotting__main__c3845fd2_plot", "plot", "1.0.1"),
            _record("skill_platform_plot", "plot", "1.0.0"),
        ]
        request = MagicMock()
        request.state.metadata = {"organization_id": "org-rhiza"}
        metadata = {
            "organization_id": "org-rhiza",
            "tool_ids": ["smap-fetch", "plot", "server:0"],
        }
        with patch("open_webui.models.tools.Tools.get_tool_catalog", return_value=[]), patch(
            "open_webui.utils.tools.accessible_skill_records", return_value=records
        ) as mock_records, patch.object(
            middleware, "get_tools", return_value={}
        ) as mock_get_tools:
            context = middleware.load_payload_context(
                request,
                SimpleNamespace(id="gen", role="user"),
                metadata,
                {"__metadata__": metadata},
                None,
                MagicMock(),
            )
        resolved = [
            "skill_weather-skills__main__c3845fd2_smap_fetch",
            "skill_weather-skills-plotting__main__c3845fd2_plot",
            "server:0",
        ]
        self.assertEqual(context.tool_ids, resolved)
        self.assertEqual(mock_records.call_args.kwargs["organization_id"], "org-rhiza")
        mock_records.assert_called_once()
        self.assertEqual(mock_get_tools.call_args.args[1], resolved)
        self.assertIs(mock_get_tools.call_args.kwargs["skill_records"], records)


class AutomationSavesSkillNamesTest(unittest.TestCase):
    def setUp(self):
        catalog = [_skill("skill_x__plot", "plot"), _skill("skill_x__smap_fetch", "smap-fetch")]
        patcher = patch(
            "open_webui.models.automations.Tools.get_tool_catalog",
            return_value=catalog,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user_id = f"user-{uuid.uuid4()}"

    def _create(self, tool_ids):
        automation = Automations.insert_new_automation(
            self.user_id,
            AutomationForm(name="Daily map", prompt="Make the map", tool_ids=tool_ids),
        )
        self.addCleanup(Automations.delete_automation, automation.id)
        return automation

    def test_create_stores_skill_names(self):
        automation = self._create(["skill_x__smap_fetch", "skill_x__plot", "server:0"])
        self.assertEqual(automation.tool_ids, ["smap-fetch", "plot", "server:0"])

    def test_create_without_tools_keeps_every_skill(self):
        self.assertIsNone(self._create(None).tool_ids)

    def test_update_stores_skill_names(self):
        automation = self._create(["skill_x__plot"])
        updated = Automations.update_automation(
            automation.id, AutomationUpdateForm(tool_ids=["plot", "skill_x__smap_fetch"])
        )
        self.assertEqual(updated.tool_ids, ["plot", "smap-fetch"])


def _load_migration():
    versions = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    path = next(versions.glob("*_automation_skill_names.py"))
    spec = importlib.util.spec_from_file_location("automation_skill_names", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationNamesTest(unittest.TestCase):
    def setUp(self):
        self.migration = _load_migration()
        self.known = ["plot", "smap-fetch", "drop", "3dpaws-fetch", "fetch", "clip-region"]

    def _convert(self, tool_ids, names_by_id=None):
        return self.migration.convert_tool_ids(tool_ids, names_by_id or {}, self.known)

    def test_existing_ids_use_their_skill_name(self):
        self.assertEqual(
            self._convert(["skill_new_plot"], {"skill_new_plot": "plot"}), (["plot"], [])
        )

    def test_stale_ids_are_matched_by_their_ending(self):
        entries, unmatched = self._convert(
            [
                "skill_plot",
                "skill_smap_fetch",
                "skill_weather-skills__dev__c3845fd2-f474-4e_drop",
                "skill_skill_3dpaws_fetch",
                "skill_weather-skills__main__c3845fd2-f474-4e_clip_region_2",
            ]
        )
        self.assertEqual(entries, ["plot", "smap-fetch", "drop", "3dpaws-fetch", "clip-region"])
        self.assertEqual(unmatched, [])

    def test_non_skill_ids_are_kept_and_unknown_skills_dropped(self):
        entries, unmatched = self._convert(["server:0", "skill_gsmap_fetch", "skill_plot"])
        self.assertEqual(entries, ["server:0", "plot"])
        self.assertEqual(unmatched, ["skill_gsmap_fetch"])


if __name__ == "__main__":
    unittest.main()
