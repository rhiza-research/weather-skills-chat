"""The stream start, skill runs, the outlet and the end of a turn read the database off the event loop."""

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from open_webui.utils import chat, middleware, skill_runtime


class StartChatResponseTest(unittest.TestCase):
    def test_stamps_the_model_then_reads_the_message(self):
        chats = MagicMock()
        chats.get_message_by_id_and_message_id.return_value = {"content": "so far"}
        with patch.object(middleware, "Chats", chats), patch.object(
            middleware, "get_sorted_filter_ids", return_value=[]
        ):
            filters, message = middleware.start_chat_response(
                {"id": "m"}, "chat-1", "msg-1", "m"
            )

        chats.upsert_message_to_chat_by_id_and_message_id.assert_called_once_with(
            "chat-1", "msg-1", {"model": "m"}, bump_revision=False
        )
        self.assertEqual(message, {"content": "so far"})
        self.assertEqual(filters, [])

    def test_without_a_saved_reply_only_filters_are_read(self):
        chats = MagicMock()
        with patch.object(middleware, "Chats", chats), patch.object(
            middleware, "get_sorted_filter_ids", return_value=[]
        ):
            _, message = middleware.start_chat_response({"id": "m"})
        chats.upsert_message_to_chat_by_id_and_message_id.assert_not_called()
        self.assertIsNone(message)


class TurnEndTest(unittest.IsolatedAsyncioTestCase):
    def _chat(self):
        messages = {
            "u1": {"id": "u1", "role": "user", "content": "Rain?", "parentId": None},
            "a1": {"id": "a1", "role": "assistant", "content": "", "parentId": "u1", "model": "m"},
        }
        return SimpleNamespace(chat={"title": "New Chat", "history": {"messages": messages}})

    def test_one_read_gives_title_and_messages(self):
        chats = MagicMock()
        chats.get_chat_by_id.return_value = self._chat()
        with patch.object(middleware, "Chats", chats):
            turn = middleware.load_turn_end("chat-1")
        chats.get_chat_by_id.assert_called_once_with("chat-1")
        self.assertEqual(turn.title, "New Chat")
        turn.finish_reply("a1", "Light rain Tuesday.")
        self.assertEqual(turn.message_map["a1"]["content"], "Light rain Tuesday.")
        self.assertTrue(turn.message_map["a1"]["done"])

    def test_a_missing_chat_has_no_title_or_messages(self):
        chats = MagicMock()
        chats.get_chat_by_id.return_value = None
        with patch.object(middleware, "Chats", chats):
            turn = middleware.load_turn_end("gone")
        self.assertIsNone(turn.title)
        self.assertEqual(turn.message_map, {})
        turn.finish_reply("a1", "x")
        self.assertEqual(turn.message_map, {})

    async def test_title_generation_uses_the_turns_read(self):
        chats = MagicMock()
        turn = middleware.TurnEnd(
            title="New Chat", message_map=self._chat().chat["history"]["messages"]
        )
        emit = AsyncMock()
        with patch.object(middleware, "Chats", chats), patch.object(
            middleware, "generate_title", AsyncMock(return_value={"choices": [{"message": {"content": '{"title": "Rain"}'}}]})
        ), patch.object(middleware, "get_event_emitter", return_value=emit):
            await middleware.emit_chat_title_if_needed(
                MagicMock(), {"model": "m"}, SimpleNamespace(id="u1"),
                {"chat_id": "chat-1", "message_id": "a1"}, turn=turn,
            )
        chats.get_chat_by_id.assert_not_called()
        chats.update_chat_title_by_id.assert_called_once_with("chat-1", "Rain")

    async def test_without_a_turn_the_chat_is_read_on_a_worker_thread(self):
        loop_thread = threading.current_thread()
        ran_on = {}

        def load(chat_id):
            ran_on["thread"] = threading.current_thread()
            return middleware.TurnEnd(title="Named", message_map={})

        with patch.object(middleware, "load_turn_end", side_effect=load):
            await middleware.emit_chat_title_if_needed(
                MagicMock(), {}, SimpleNamespace(id="u1"), {"chat_id": "c", "message_id": "m"}
            )
        self.assertIsNot(ran_on["thread"], loop_thread)

    async def test_the_revision_is_read_on_a_worker_thread(self):
        loop_thread = threading.current_thread()
        ran_on = {}

        def revision(chat_id):
            ran_on["thread"] = threading.current_thread()
            return 7

        chats = MagicMock()
        chats.get_chat_revision.side_effect = revision
        with patch.object(middleware, "Chats", chats):
            self.assertEqual(await middleware.completion_revision("chat-1"), 7)
        self.assertIsNot(ran_on["thread"], loop_thread)


class OutletTest(unittest.IsolatedAsyncioTestCase):
    async def test_model_and_filters_are_looked_up_on_a_worker_thread(self):
        loop_thread = threading.current_thread()
        ran_on = {}

        def filters(model):
            ran_on["thread"] = threading.current_thread()
            return []

        request = SimpleNamespace(
            state=SimpleNamespace(),
            app=SimpleNamespace(state=SimpleNamespace(MODELS={"m": {"id": "m"}})),
        )
        form = {"model": "m", "messages": [], "chat_id": "c", "session_id": "s", "id": "a1"}
        with patch.object(chat, "get_sorted_filter_ids", side_effect=filters), patch.object(
            chat, "remember_catalog_model"
        ), patch.object(
            chat, "process_pipeline_outlet_filter", AsyncMock(side_effect=lambda r, d, u, m: d)
        ):
            result = await chat.chat_completed(request, form, SimpleNamespace(id="u1", email="", name="", role="user"))

        self.assertEqual(result["id"], "a1")
        self.assertIsNot(ran_on["thread"], loop_thread)

    def test_a_filter_lookup_error_is_returned_not_raised(self):
        request = SimpleNamespace(
            state=SimpleNamespace(),
            app=SimpleNamespace(state=SimpleNamespace(MODELS={"m": {"id": "m"}})),
        )
        with patch.object(chat, "get_sorted_filter_ids", side_effect=RuntimeError("db down")), patch.object(
            chat, "remember_catalog_model"
        ):
            *_, filter_error = chat.start_chat_outlet(request, {"model": "m"})
        self.assertIsInstance(filter_error, RuntimeError)


class SkillRunTest(unittest.IsolatedAsyncioTestCase):
    async def test_setup_runs_on_a_worker_thread(self):
        loop_thread = threading.current_thread()
        ran_on = {}

        def secrets(names, user, organization_id=None):
            ran_on["thread"] = threading.current_thread()
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "skill"
            (skill / "scripts").mkdir(parents=True)
            (skill / "scripts" / "run.py").write_text("print('hi')\n")
            with patch.object(skill_runtime, "resolve_env_secrets_for_user", side_effect=secrets):
                run = await asyncio.to_thread(skill_runtime.prepare_skill_run, skill)
                with patch.object(
                    skill_runtime, "prepare_skill_run", side_effect=lambda *a: {"error": "stop"}
                ):
                    result = await skill_runtime.run_skill(skill)

        self.assertIsInstance(run, skill_runtime.SkillRun)
        self.assertEqual(run.script_path.name, "run.py")
        self.assertIsNot(ran_on["thread"], loop_thread)
        self.assertEqual(result, {"error": "stop"})

    def test_a_missing_skill_is_an_error_result(self):
        result = skill_runtime.prepare_skill_run("/nonexistent/skill")
        self.assertIsInstance(result, dict)
        self.assertIn("not found", str(result))


if __name__ == "__main__":
    unittest.main()
