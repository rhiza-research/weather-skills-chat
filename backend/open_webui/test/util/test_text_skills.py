"""Text skills: splitting them from tool ids, the prompt block, and the size cap."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError


def _row(id, title, content, enabled=True):
    return SimpleNamespace(id=id, title=title, content=content, enabled=enabled)


class TextSkillTest(unittest.TestCase):
    def test_split_keeps_tools_and_strips_prefix(self):
        from open_webui.utils.text_skills import split_text_skill_ids

        tools, skills = split_text_skill_ids(["plot", "text_skill:a", "text_skill:b"])
        self.assertEqual(tools, ["plot"])
        self.assertEqual(skills, ["a", "b"])
        self.assertEqual(split_text_skill_ids(None), (None, []))

    def test_prompt_has_whole_markdown_of_chosen_enabled_skills(self):
        from open_webui.utils.text_skills import text_skills_prompt

        report = "---\nname: report\n---\n# Report\n\n## Sections\nSummary first."
        rows = [
            _row("a", "Report", report),
            _row("b", "Off", "Hidden.", enabled=False),
            _row("c", "Not chosen", "Also hidden."),
        ]
        user = SimpleNamespace(id="user-1")
        with patch(
            "open_webui.utils.text_skills.TextSkills.list_for_org", return_value=rows
        ) as list_for_org:
            prompt = text_skills_prompt(user, "org-1", ["a", "b", "x"])

        list_for_org.assert_called_once_with("org-1", "user-1")
        self.assertIn("### Report", prompt)
        self.assertIn(report, prompt)
        self.assertNotIn("Hidden.", prompt)
        self.assertNotIn("Also hidden.", prompt)
        self.assertEqual(text_skills_prompt(user, "org-1", []), "")

    def test_inject_replaces_previous_block_and_keeps_preferences(self):
        from open_webui.utils.preferences import inject_preferences
        from open_webui.utils.text_skills import inject_text_skills

        old = "## Skills\nx\n\n### A\nOld text.\n\n## End skills"
        new = "## Skills\nx\n\n### A\nNew text.\n\n## End skills"
        prefs = "## Saved preferences\n### Units\nmm\n## End saved preferences"
        messages = [{"role": "system", "content": f"Model prompt\n\n{old}"}]
        messages = inject_preferences(messages, prefs)
        messages = inject_text_skills(messages, new)
        content = messages[0]["content"]
        self.assertTrue(content.startswith("Model prompt"))
        self.assertIn("New text.", content)
        self.assertNotIn("Old text.", content)
        self.assertEqual(content.count("## Skills"), 1)
        self.assertIn("## Saved preferences", content)

        # No skills chosen: the old block goes and nothing new is added.
        cleared = inject_text_skills(messages, "")
        self.assertNotIn("## Skills", cleared[0]["content"])
        self.assertEqual(inject_text_skills([], ""), [])

    def test_size_cap(self):
        from open_webui.models.text_skills import (
            MAX_TEXT_SKILL_CONTENT_BYTES,
            TextSkillForm,
            TextSkillUpdateForm,
        )

        TextSkillForm(title="Ok", content="a" * MAX_TEXT_SKILL_CONTENT_BYTES)
        with self.assertRaises(ValidationError):
            TextSkillForm(title="Big", content="a" * (MAX_TEXT_SKILL_CONTENT_BYTES + 1))
        with self.assertRaises(ValidationError):
            TextSkillUpdateForm(content="   ")
        with self.assertRaises(ValidationError):
            TextSkillForm(title=" ", content="x")


class TextSkillShareTest(unittest.TestCase):
    def test_only_org_admins_share_and_not_in_personal_org(self):
        from fastapi import HTTPException
        from open_webui.routers import text_skills as router

        with patch.object(router, "is_personal_org", return_value=True):
            with self.assertRaises(HTTPException) as err:
                router._check_share("org-1", "user-1")
            self.assertEqual(err.exception.status_code, 400)
        with patch.object(router, "is_personal_org", return_value=False), patch.object(
            router, "is_org_admin", return_value=False
        ):
            with self.assertRaises(HTTPException) as err:
                router._check_share("org-1", "user-1")
            self.assertEqual(err.exception.status_code, 403)
        with patch.object(router, "is_personal_org", return_value=False), patch.object(
            router, "is_org_admin", return_value=True
        ):
            router._check_share("org-1", "user-1")


if __name__ == "__main__":
    unittest.main()
