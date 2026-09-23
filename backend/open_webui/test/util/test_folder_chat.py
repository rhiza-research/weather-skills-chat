"""Which chats can be filed in private vs team folders."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.routers.folders import _folder_chat_items_by_folder
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


class FolderChatBatchTest(unittest.TestCase):
    def test_one_query_per_visibility_and_one_owner_lookup(self):
        folders = [
            SimpleNamespace(id="p1", visibility="private"),
            SimpleNamespace(id="p2", visibility="private"),
            SimpleNamespace(id="o1", visibility="organization"),
        ]
        user = SimpleNamespace(id="alice")
        chats = [
            SimpleNamespace(
                id="c1",
                title="Mine",
                user_id="alice",
                visibility="private",
                folder_id="p1",
            ),
            SimpleNamespace(
                id="c2",
                title="Team",
                user_id="bob",
                visibility="organization",
                folder_id="o1",
            ),
        ]
        calls = []

        def fake_get(folder_ids, user_id, visibility):
            calls.append((list(folder_ids), user_id, visibility))
            return [chat for chat in chats if chat.folder_id in folder_ids]

        with patch(
            "open_webui.routers.folders.Chats.get_chats_in_folders",
            side_effect=fake_get,
        ), patch(
            "open_webui.routers.folders.Users.get_users_by_user_ids",
            return_value=[
                SimpleNamespace(id="alice", name="Alice"),
                SimpleNamespace(id="bob", name="Bob"),
            ],
        ) as mock_users:
            items = _folder_chat_items_by_folder(folders, user)

        self.assertEqual(
            calls,
            [
                (["p1", "p2"], "alice", "private"),
                (["o1"], "alice", "organization"),
            ],
        )
        mock_users.assert_called_once()
        self.assertEqual(items["p1"][0]["owner_name"], "Alice")
        self.assertEqual(items["o1"][0]["owner_name"], "Bob")
        self.assertNotIn("p2", items)


if __name__ == "__main__":
    unittest.main()
