"""Tests for loading skill tools on demand through skill_search."""

from __future__ import annotations

import asyncio
import json
import unittest

from open_webui.routers.openai import enable_openrouter_prompt_caching
from open_webui.utils.deferred_tools import (
    SKILL_SEARCH,
    add_skill_search,
    apply_deferred_tools,
    defer_tools,
)


def _skill(name, description):
    return {"tool_id": f"pack--{name}", "spec": {"name": name, "description": description}}


def _tools_dict():
    return {
        "plot": _skill("plot", "Draw a figure"),
        "standardize_anomaly": _skill("standardize_anomaly", "Z-score anomaly against a climatology"),
        "imerg_fetch": _skill("imerg_fetch", "Fetch IMERG rainfall"),
        "list_artifacts": {"toolkit_id": "builtin", "spec": {"name": "list_artifacts"}},
    }


def _openai_tools(tools_dict, deferred):
    return defer_tools(
        [{"type": "function", "function": dict(t["spec"])} for t in tools_dict.values()],
        deferred,
    )


def _names(tools, deferred):
    return [
        t["function"]["name"]
        for t in tools
        if bool(t["function"].get("defer_loading")) is deferred
    ]


class DeferredToolsTest(unittest.TestCase):
    def test_every_skill_is_deferred_and_builtins_are_not(self):
        tools_dict = _tools_dict()
        deferred = add_skill_search(tools_dict)
        self.assertEqual(deferred, {"plot", "standardize_anomaly", "imerg_fetch"})
        self.assertIn(SKILL_SEARCH, tools_dict)

    def test_search_matches_whole_words_not_substrings(self):
        tools_dict = _tools_dict()
        add_skill_search(tools_dict)
        search = tools_dict[SKILL_SEARCH]["callable"]
        self.assertEqual(json.loads(asyncio.run(search(query="an")))["found"], [])

    def test_search_ranks_name_matches_first(self):
        tools_dict = _tools_dict()
        add_skill_search(tools_dict)
        search = tools_dict[SKILL_SEARCH]["callable"]
        found = json.loads(asyncio.run(search(query="standardized anomaly z-score")))["found"]
        self.assertEqual(found[0], "standardize_anomaly")
        self.assertNotIn("plot", found)

    def test_found_and_called_tools_load_and_the_rest_go_last(self):
        tools_dict = _tools_dict()
        tools = _openai_tools(tools_dict, add_skill_search(tools_dict))
        messages = [
            {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": SKILL_SEARCH}}]},
            {"role": "tool", "tool_call_id": "c1", "content": json.dumps({"found": ["standardize_anomaly"]})},
        ]
        out = apply_deferred_tools({"tools": tools, "messages": messages}, defer=True)["tools"]
        self.assertEqual(sorted(_names(out, deferred=True)), ["imerg_fetch", "plot"])
        self.assertTrue(out[-1]["function"].get("defer_loading"))
        self.assertIn("standardize_anomaly", _names(out, deferred=False))

    def test_other_providers_get_every_tool_in_full(self):
        tools_dict = _tools_dict()
        tools = _openai_tools(tools_dict, add_skill_search(tools_dict))
        out = apply_deferred_tools({"tools": tools, "messages": []}, defer=False)["tools"]
        self.assertEqual(_names(out, deferred=True), [])

    def test_cache_breakpoint_skips_deferred_tools(self):
        tools_dict = _tools_dict()
        tools = _openai_tools(tools_dict, add_skill_search(tools_dict))
        payload = apply_deferred_tools(
            {"model": "anthropic/claude-opus-5.5", "tools": tools, "messages": []}, defer=True
        )
        out = enable_openrouter_prompt_caching("https://openrouter.ai/api/v1", payload)["tools"]
        marked = [t["function"]["name"] for t in out if "cache_control" in t]
        self.assertEqual(len(marked), 1)
        self.assertNotIn(marked[0], {"plot", "standardize_anomaly", "imerg_fetch"})


if __name__ == "__main__":
    unittest.main()
