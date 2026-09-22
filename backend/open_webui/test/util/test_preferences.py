"""Preference prompt injection and create-tool instructions."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch


class PreferencePromptTest(unittest.TestCase):
    def test_prompt_includes_only_enabled_and_replaces_previous_block(self):
        from open_webui.utils.preferences import inject_preferences, preferences_prompt

        user = SimpleNamespace(id="user-1")
        with patch(
            "open_webui.utils.preferences.list_preference_metadata",
            return_value=[
                {
                    "title": "Units",
                    "content": "Use millimeters.",
                    "visibility": "private",
                    "enabled": True,
                },
                {
                    "title": "Region",
                    "content": "Default to Kenya.",
                    "visibility": "organization",
                    "enabled": False,
                },
            ],
        ):
            prompt = preferences_prompt(user, "org-1")

        self.assertIn("### Units (private)", prompt)
        self.assertIn("Use millimeters.", prompt)
        self.assertNotIn("Kenya", prompt)
        self.assertTrue(prompt.startswith("## Saved preferences"))
        self.assertTrue(prompt.endswith("## End saved preferences"))

        messages = [{"role": "system", "content": f"Model prompt\n\n{prompt}"}]
        with patch(
            "open_webui.utils.preferences.list_preference_metadata",
            return_value=[
                {
                    "title": "Units",
                    "content": "Use inches.",
                    "visibility": "private",
                    "enabled": True,
                }
            ],
        ):
            updated = preferences_prompt(user, "org-1")
        messages = inject_preferences(messages, updated)
        self.assertIn("Use inches.", messages[0]["content"])
        self.assertNotIn("Use millimeters.", messages[0]["content"])
        self.assertEqual(messages[0]["content"].count("## Saved preferences"), 1)

    def test_create_tool_asks_before_saving(self):
        from open_webui.utils.builtin_tools import CREATE_PREFERENCE_SPEC

        description = CREATE_PREFERENCE_SPEC["description"].lower()
        self.assertIn("ask the user", description)
        self.assertIn("agree", description)
        self.assertIn("do not create", description)


if __name__ == "__main__":
    unittest.main()
