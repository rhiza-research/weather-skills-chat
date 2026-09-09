"""The account's endpoint session is looked up on each call, not stored.

The stores available for keeping a session id accept arbitrary values from the account, so a
stored id could point at another account's row. These tests check that no id is stored, that the
lookup compares the owner and the organization, and that two concurrent first calls end with one
session.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastmcp.exceptions import ToolError

from open_webui.mcp.session import (
    SESSION_MARKER_KEY,
    SESSION_TITLE,
    owned_session,
    session_id,
)

ACCOUNT = SimpleNamespace(id="account-1", role="user")
OTHER = SimpleNamespace(id="account-2", role="user")
ORG = "org-1"
OTHER_ORG = "org-2"


def chat(chat_id, user_id, created_at, marked=True, extra=None, organization_id=ORG):
    blob = {"title": "t"}
    if marked:
        blob[SESSION_MARKER_KEY] = True
    if extra:
        blob.update(extra)
    return SimpleNamespace(
        id=chat_id,
        user_id=user_id,
        created_at=created_at,
        chat=blob,
        organization_id=organization_id,
        visibility="private",
    )


class FindsAnExistingSessionTest(unittest.TestCase):
    def resolve(self, rows, account=ACCOUNT):
        with patch(
            "open_webui.mcp.session.Chats.get_chats_by_user_id", return_value=rows
        ), patch("open_webui.mcp.session.Chats.insert_new_chat") as insert:
            return owned_session(account, ORG), insert

    def test_a_marked_owned_row_is_reused(self):
        found, insert = self.resolve([chat("c1", ACCOUNT.id, 100)])
        self.assertEqual(found.id, "c1")
        insert.assert_not_called()

    def test_an_unmarked_row_is_not_a_session(self):
        # An ordinary chat is not used as the session.
        rows = [chat("c1", ACCOUNT.id, 100, marked=False)]
        with patch(
            "open_webui.mcp.session.Chats.get_chats_by_user_id", return_value=rows
        ), patch(
            "open_webui.mcp.session.Chats.insert_new_chat",
            return_value=chat("new", ACCOUNT.id, 200),
        ):
            with patch(
                "open_webui.mcp.session._existing",
                side_effect=[None, chat("new", ACCOUNT.id, 200)],
            ):
                self.assertEqual(owned_session(ACCOUNT, ORG).id, "new")

    def test_a_row_owned_by_somebody_else_is_never_adopted(self):
        # The store query is already scoped by account. The owner is checked again on each row.
        rows = [chat("theirs", OTHER.id, 100)]
        with patch(
            "open_webui.mcp.session.Chats.get_chats_by_user_id", return_value=rows
        ), patch(
            "open_webui.mcp.session.Chats.insert_new_chat",
            return_value=chat("mine", ACCOUNT.id, 200),
        ), patch(
            "open_webui.mcp.session.Chats.delete_chat_by_id_and_user_id"
        ):
            with patch(
                "open_webui.mcp.session._existing",
                side_effect=[None, chat("mine", ACCOUNT.id, 200)],
            ):
                self.assertEqual(owned_session(ACCOUNT, ORG).id, "mine")

    def test_a_session_in_another_organization_is_not_reused(self):
        # Each organization has its own session, so runs in one never share a directory with runs
        # in another.
        rows = [chat("elsewhere", ACCOUNT.id, 100, organization_id=OTHER_ORG)]
        created = chat("here", ACCOUNT.id, 200)
        with patch(
            "open_webui.mcp.session.Chats.get_chats_by_user_id",
            side_effect=[rows, [*rows, created]],
        ), patch(
            "open_webui.mcp.session.Chats.insert_new_chat", return_value=created
        ) as insert, patch(
            "open_webui.mcp.session.Chats.delete_chat_by_id_and_user_id"
        ) as delete:
            self.assertEqual(owned_session(ACCOUNT, ORG).id, "here")
        insert.assert_called_once()
        delete.assert_not_called()

    def test_the_oldest_marked_row_wins(self):
        rows = [
            chat("newer", ACCOUNT.id, 300),
            chat("oldest", ACCOUNT.id, 100),
            chat("middle", ACCOUNT.id, 200),
        ]
        found, _ = self.resolve(rows)
        self.assertEqual(found.id, "oldest")

    def test_a_tie_on_time_is_broken_deterministically(self):
        # Rows with the same created_at are ordered by id.
        rows = [chat("b", ACCOUNT.id, 100), chat("a", ACCOUNT.id, 100)]
        found, _ = self.resolve(rows)
        self.assertEqual(found.id, "a")


class CreatesOnFirstUseTest(unittest.TestCase):
    def test_the_created_row_is_a_private_marked_chat_in_the_organization(self):
        created = chat("new", ACCOUNT.id, 100)
        with patch(
            "open_webui.mcp.session.Chats.get_chats_by_user_id",
            side_effect=[[], [created]],
        ), patch(
            "open_webui.mcp.session.Chats.insert_new_chat", return_value=created
        ) as insert:
            owned_session(ACCOUNT, ORG)
        form = insert.call_args.args[1]
        self.assertEqual(form.organization_id, ORG)
        self.assertEqual(form.visibility, "private")
        self.assertTrue(form.chat[SESSION_MARKER_KEY])
        self.assertEqual(form.chat["title"], SESSION_TITLE)
        self.assertEqual(SESSION_TITLE, "MCP session")

    def test_a_failed_insert_refuses_rather_than_returning_nothing(self):
        with patch(
            "open_webui.mcp.session.Chats.get_chats_by_user_id", return_value=[]
        ), patch("open_webui.mcp.session.Chats.insert_new_chat", return_value=None):
            with self.assertRaises(ToolError):
                owned_session(ACCOUNT, ORG)


class ConcurrentFirstCallTest(unittest.TestCase):
    def test_the_loser_adopts_the_winner_and_removes_its_own_row(self):
        mine = chat("mine", ACCOUNT.id, 200)
        theirs = chat("theirs", ACCOUNT.id, 100)
        with patch(
            "open_webui.mcp.session.Chats.get_chats_by_user_id",
            side_effect=[[], [theirs, mine]],
        ), patch(
            "open_webui.mcp.session.Chats.insert_new_chat", return_value=mine
        ), patch(
            "open_webui.mcp.session.Chats.delete_chat_by_id_and_user_id"
        ) as delete:
            self.assertEqual(owned_session(ACCOUNT, ORG).id, "theirs")
        delete.assert_called_once_with("mine", ACCOUNT.id)

    def test_the_winner_keeps_its_row(self):
        mine = chat("mine", ACCOUNT.id, 100)
        with patch(
            "open_webui.mcp.session.Chats.get_chats_by_user_id",
            side_effect=[[], [mine]],
        ), patch(
            "open_webui.mcp.session.Chats.insert_new_chat", return_value=mine
        ), patch(
            "open_webui.mcp.session.Chats.delete_chat_by_id_and_user_id"
        ) as delete:
            self.assertEqual(owned_session(ACCOUNT, ORG).id, "mine")
        delete.assert_not_called()


class NoPointerIsKeptTest(unittest.TestCase):
    def test_the_module_writes_to_no_account_settings_store(self):
        import ast
        import pathlib

        from open_webui.mcp import session

        source = pathlib.Path(session.__file__).read_text()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Attribute):
                self.assertNotIn(
                    node.attr,
                    ("update_user_settings_by_id", "update_user_by_id"),
                    "the session module writes to an account settings store",
                )


class SessionIdTest(unittest.TestCase):
    def test_the_id_is_the_row_id(self):
        # The row id is also the artifact directory name.
        row = chat("c1", ACCOUNT.id, 100)
        with patch("open_webui.mcp.session.owned_session", return_value=row):
            self.assertEqual(session_id(ACCOUNT, ORG), "c1")


if __name__ == "__main__":
    unittest.main()
