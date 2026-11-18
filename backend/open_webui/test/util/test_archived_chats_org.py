"""Archived chats are listed and archived per active organization."""

import unittest
import uuid

import open_webui.config  # noqa: F401  Runs the migrations.
from open_webui.models.chats import ChatForm, Chats


class ArchivedChatsOrgTest(unittest.TestCase):
    def setUp(self):
        self.user = f"user-{uuid.uuid4()}"
        self.org = f"org-{uuid.uuid4()}"
        self.personal = self._chat(None)
        self.team = self._chat(self.org)

    def _chat(self, organization_id):
        chat = Chats.insert_new_chat(
            self.user,
            ChatForm(chat={"title": "Rain"}, organization_id=organization_id),
        )
        self.addCleanup(Chats.delete_chat_by_id, chat.id)
        return chat

    def _archived(self, organization_id):
        return {
            c.id
            for c in Chats.get_archived_chat_list_by_user_id(self.user, organization_id)
        }

    def test_archive_all_and_list_stay_in_the_active_org(self):
        self.assertTrue(Chats.archive_all_chats_by_user_id(self.user, self.org))

        self.assertEqual(self._archived(self.org), {self.team.id})
        self.assertEqual(self._archived(self.user), set())

    def test_each_org_lists_only_its_own_archived_chats(self):
        Chats.archive_all_chats_by_user_id(self.user, self.org)
        Chats.archive_all_chats_by_user_id(self.user, self.user)

        self.assertEqual(self._archived(self.org), {self.team.id})
        self.assertEqual(self._archived(self.user), {self.personal.id})


if __name__ == "__main__":
    unittest.main()
