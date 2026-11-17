"""Tests for serving skills through read_skill and run_skill."""

from __future__ import annotations

import asyncio
import unittest

from open_webui.utils.skill_tools import READ_SKILL, RUN_SKILL, add_skill_tools, call_name
from open_webui.utils.tool_parallel import execution_waves

PARAMS = {
    "type": "object",
    "properties": {"argv": {"type": "array", "items": {"type": "string"}}},
}


def _skill(name, description):
    async def run(**kwargs):
        return {"skill": name, **kwargs}

    return {
        "tool_id": f"pack--{name}",
        "kind": "skill",
        "callable": run,
        "spec": {"name": name, "description": description, "parameters": PARAMS},
    }


def _tools_dict():
    return {
        "plot": _skill("plot", "Draw a figure.\n\nUsage: plot.py -i IN -o OUT"),
        "standardize_anomaly": _skill("standardize_anomaly", "Z-score anomaly against a climatology"),
        "imerg_fetch": _skill("imerg_fetch", "Fetch IMERG rainfall"),
        "list_artifacts": {"toolkit_id": "builtin", "spec": {"name": "list_artifacts"}},
    }


def _call(tools_dict, name, **kwargs):
    return asyncio.run(tools_dict[name]["callable"](**kwargs))


class SkillToolsTest(unittest.TestCase):
    def test_skills_are_served_and_builtins_are_not(self):
        tools_dict = _tools_dict()
        skills = add_skill_tools(tools_dict)
        self.assertEqual(skills, {"plot", "standardize_anomaly", "imerg_fetch"})
        self.assertIn(READ_SKILL, tools_dict)
        self.assertIn(RUN_SKILL, tools_dict)

    def test_tool_server_and_workspace_tools_keep_their_own_schema(self):
        tools_dict = _tools_dict()
        tools_dict["get_station"] = {
            "tool_id": "server:0",
            "spec": {
                "name": "get_station",
                "parameters": {"type": "object", "properties": {"station_id": {"type": "string"}}},
            },
        }
        tools_dict["a_workspace_tool"] = {
            "tool_id": "my_tools",
            "kind": None,
            "spec": {"name": "a_workspace_tool", "parameters": {"type": "object", "properties": {"q": {}}}},
        }
        skills = add_skill_tools(tools_dict)
        self.assertEqual(skills, {"plot", "standardize_anomaly", "imerg_fetch"})
        params = tools_dict[RUN_SKILL]["spec"]["parameters"]
        self.assertEqual(list(params["properties"]), ["skill", "argv"])

    def test_read_skill_returns_each_named_skills_instructions(self):
        tools_dict = _tools_dict()
        add_skill_tools(tools_dict)
        text = _call(tools_dict, READ_SKILL, names=["plot", "imerg_fetch"])
        self.assertEqual(
            text,
            "## plot\nDraw a figure.\n\nUsage: plot.py -i IN -o OUT\n\n## imerg_fetch\nFetch IMERG rainfall",
        )

    def test_read_skill_takes_one_name_as_a_string(self):
        tools_dict = _tools_dict()
        add_skill_tools(tools_dict)
        self.assertTrue(_call(tools_dict, READ_SKILL, names="plot").startswith("## plot\n"))

    def test_read_skill_suggests_a_close_name(self):
        tools_dict = _tools_dict()
        add_skill_tools(tools_dict)
        text = _call(tools_dict, READ_SKILL, names=["plots"])
        self.assertIn("No skill `plots`", text)
        self.assertIn("Did you mean plot", text)

    def test_run_skill_calls_the_skill_with_its_arguments(self):
        tools_dict = _tools_dict()
        add_skill_tools(tools_dict)
        out = _call(tools_dict, RUN_SKILL, skill="plot", argv=["--help"])
        self.assertEqual(out, {"skill": "plot", "argv": ["--help"]})

    def test_run_skill_suggests_a_close_name(self):
        tools_dict = _tools_dict()
        add_skill_tools(tools_dict)
        out = _call(tools_dict, RUN_SKILL, skill="plots", argv=[])
        self.assertIn("No skill `plots`", out)
        self.assertIn("Did you mean plot", out)

    def test_run_skill_takes_the_skills_arguments_plus_skill(self):
        tools_dict = _tools_dict()
        add_skill_tools(tools_dict)
        params = tools_dict[RUN_SKILL]["spec"]["parameters"]
        self.assertEqual(list(params["properties"]), ["skill", "argv"])
        self.assertEqual(params["required"], ["skill"])

    def test_depends_on_a_skill_name_waits_for_that_run_skill_call(self):
        calls = [("run_skill", {"skill": "select"}), ("run_skill", {"skill": "label_group"})]
        names = [call_name(n, p) for n, p in calls]
        self.assertEqual(names, ["select", "label_group"])
        self.assertEqual(execution_waves(["a", "b"], names, [[], ["select"]]), [[0], [1]])

    def test_call_name_keeps_other_tools_names(self):
        self.assertEqual(call_name("display_image", {"skill": "x"}), "display_image")
        self.assertEqual(call_name("run_skill", {}), "run_skill")


if __name__ == "__main__":
    unittest.main()
