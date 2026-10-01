"""Chat tool list stays small: no avatar, no skill filesystem details."""

import unittest

from open_webui.models.tools import ToolChatResponse, ToolMeta, ToolOwnerResponse
from open_webui.routers.tools import _chat_tool


class ToolChatPayloadTest(unittest.TestCase):
    def test_owner_drops_avatar_and_secrets(self):
        owner = ToolOwnerResponse.model_validate(
            {
                "id": "u",
                "name": "Ada",
                "email": "ada@example.com",
                "role": "user",
                "profile_image_url": "data:image/png;base64,AAAA",
                "api_key": "secret",
                "settings": {"ui": {}},
            }
        )
        dumped = owner.model_dump()
        self.assertEqual(
            set(dumped),
            {"id", "name", "email", "role"},
        )

    def test_chat_view_keeps_selection_fields_only(self):
        tool = type("Tool", (), {})()
        tool.id = "skill_x"
        tool.name = "x@1"
        tool.meta = ToolMeta(
            description="rain",
            manifest={
                "kind": "skill",
                "skill_name": "x",
                "version": "1",
                "git_ref": "main",
                "git_url": "https://github.com/o/r.git",
                "enabled": True,
                "skill_dir": "/huge/path",
                "scripts": ["a.py"],
                "commit_sha": "abc",
                "pack_id": "pack",
                "relative_path": "skills/x",
            },
        )
        view = ToolChatResponse.model_validate(_chat_tool(tool)).model_dump()
        self.assertEqual(set(view), {"id", "name", "meta"})
        self.assertNotIn("user", view)
        manifest = view["meta"]["manifest"]
        self.assertEqual(
            set(manifest),
            {"kind", "skill_name", "version", "git_ref", "git_url", "enabled"},
        )
        self.assertEqual(manifest["skill_name"], "x")
        self.assertEqual(view["meta"]["description"], "rain")


if __name__ == "__main__":
    unittest.main()
