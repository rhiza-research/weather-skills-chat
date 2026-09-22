"""Which chats can be filed in private vs team folders."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from open_webui.utils.organizations import folder_chat_error


def _folder(**kwargs):
    defaults = {
        "visibility": "private",
        "user_id": "owner",
        "organization_id": "org-1",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _chat(**kwargs):
    defaults = {
        "visibility": "private",
        "user_id": "owner",
        "organization_id": "org-1",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class FolderChatErrorTest(unittest.TestCase):
    def test_private_chat_fits_owners_private_folder(self):
        self.assertIsNone(folder_chat_error(_folder(), _chat()))

    def test_team_chat_fits_team_folder(self):
        self.assertIsNone(
            folder_chat_error(
                _folder(visibility="organization", user_id="someone-else"),
                _chat(visibility="organization", user_id="owner"),
            )
        )

    def test_private_chat_cannot_enter_team_folder(self):
        error = folder_chat_error(
            _folder(visibility="organization"),
            _chat(visibility="private"),
        )
        self.assertIn("Share the chat", error)

    def test_team_chat_cannot_enter_private_folder(self):
        error = folder_chat_error(
            _folder(visibility="private"),
            _chat(visibility="organization"),
        )
        self.assertIn("team folders", error)

    def test_team_folder_rejects_other_organization(self):
        error = folder_chat_error(
            _folder(visibility="organization", organization_id="org-1"),
            _chat(visibility="organization", organization_id="org-2"),
        )
        self.assertIn("different organization", error)


if __name__ == "__main__":
    unittest.main()
