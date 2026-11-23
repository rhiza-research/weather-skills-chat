import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from open_webui.models.chats import Chats
from open_webui.utils import chat_compaction as cc
from open_webui.utils.chat_turns import messages_for_model


def _chat(**reply_fields):
    return {
        "chatNotes": ["NOTE"],
        "history": {
            "currentId": "a2",
            "messages": {
                "u1": {"id": "u1", "parentId": None, "childrenIds": ["a1"], "role": "user", "content": "first"},
                "a1": {
                    "id": "a1",
                    "parentId": "u1",
                    "childrenIds": ["u2"],
                    "role": "assistant",
                    "content": "first answer",
                    **reply_fields,
                },
                "u2": {"id": "u2", "parentId": "a1", "childrenIds": ["a2"], "role": "user", "content": "second"},
                "a2": {"id": "a2", "parentId": "u2", "childrenIds": [], "role": "assistant", "content": "second answer"},
            },
        },
    }


class MessagesForModelCutTest(unittest.TestCase):
    def test_done_compaction_replaces_earlier_messages_with_its_summary(self):
        chat = _chat(compaction={"status": "done", "summary": "SUMMARY"})
        messages = messages_for_model(chat, "a2")
        self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
        first = messages[0]["content"]
        self.assertTrue(first.startswith("Earlier messages"))
        self.assertIn("SUMMARY", first)
        self.assertIn("second", first)
        self.assertIn("NOTE", first)
        self.assertNotIn("first", first)

    def test_running_compaction_changes_nothing(self):
        chat = _chat(compaction={"status": "running", "started_at": 1})
        self.assertEqual(len(messages_for_model(chat, "a2")), 4)

    def test_a_branch_before_the_compaction_is_not_cut(self):
        chat = _chat(compaction={"status": "done", "summary": "SUMMARY"})
        messages = chat["history"]["messages"]
        messages["u1"]["childrenIds"].append("b1")
        messages["b1"] = {"id": "b1", "parentId": "u1", "childrenIds": [], "role": "assistant", "content": "retry"}
        self.assertEqual([m["content"] for m in messages_for_model(chat, "b1")][1], "retry")


class EstimateTest(unittest.TestCase):
    def test_estimate_removes_the_transcript_and_adds_the_summary(self):
        instructions = len(cc.SUMMARY_INSTRUCTIONS) // cc.CHARS_PER_TOKEN
        result = cc.compaction_estimate(
            {"context_used": 180_000, "context_window": 200_000},
            {"prompt_tokens": 150_000 + instructions, "completion_tokens": 2_000},
        )
        self.assertEqual(result, {"context_estimate": 32_000, "context_window": 200_000})

    def test_no_usage_gives_no_estimate(self):
        self.assertEqual(cc.compaction_estimate(None, {"prompt_tokens": 1, "completion_tokens": 1}), {})

    def test_running_goes_stale_after_the_timeout(self):
        now = time.time()
        self.assertTrue(cc.compaction_running({"status": "running", "started_at": now - 10}, now))
        self.assertFalse(
            cc.compaction_running(
                {"status": "running", "started_at": now - cc.COMPACTION_TIMEOUT_S - 1}, now
            )
        )
        self.assertFalse(cc.compaction_running({"status": "done"}, now))


class CallShapeTest(unittest.TestCase):
    def test_compacted_messages_keep_system_and_the_current_turn(self):
        messages = [
            {"role": "system", "content": "SYS"},
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "old answer"},
            {"role": "user", "content": "now"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t"}]},
            {"role": "tool", "content": "result"},
        ]
        out = cc.compacted_messages(messages, "SUMMARY", "NOTE")
        self.assertEqual([m["role"] for m in out], ["system", "user", "assistant", "tool"])
        self.assertTrue(out[1]["content"].startswith("Earlier messages"))
        self.assertIn("now", out[1]["content"])
        self.assertIn("NOTE", out[1]["content"])
        self.assertEqual(messages[3]["content"], "now")

    def test_oldest_tool_results_are_dropped_until_the_call_fits(self):
        messages = [
            {"role": "user", "content": "go"},
            {"role": "tool", "content": "a" * 4000},
            {"role": "tool", "content": "b" * 4000},
            {"role": "tool", "content": "c" * 4000},
        ]
        # 12002 chars is 3000 tokens; a 2100-token window needs one result gone.
        out = cc._drop_old_tool_results(messages, None, 0, 2100)
        self.assertEqual(out[1]["content"], cc.TOOL_RESULT_REMOVED)
        self.assertEqual(out[2]["content"], "b" * 4000)
        self.assertEqual(messages[1]["content"], "a" * 4000)

    def test_transcript_text_flattens_tool_turns(self):
        text = cc.transcript_text(
            [
                {"role": "user", "content": "plot rain"},
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"id": "t", "function": {"name": "plot", "arguments": "{}"}}],
                },
                {"role": "tool", "tool_call_id": "t", "content": "/out/rain.png"},
            ]
        )
        self.assertIn("USER:\nplot rain", text)
        self.assertIn("ASSISTANT CALLED plot: {}", text)
        self.assertIn("TOOL RESULT:\n/out/rain.png", text)


class SetMessageCompactionTest(unittest.TestCase):
    def _write(self, document, **kwargs):
        def fake(_id, apply, **_kw):
            apply(document, None)
            return None, "ok"

        with patch.object(Chats, "_write_locked_chat", side_effect=fake):
            return Chats.set_message_compaction("c", "a1", {"status": "done"}, **kwargs)

    def test_writes_while_the_replies_are_unchanged(self):
        document = _chat()
        self.assertTrue(self._write(document, children=["u2"]))
        self.assertEqual(document["history"]["messages"]["a1"]["compaction"], {"status": "done"})

    def test_a_new_reply_wins_over_the_compaction(self):
        document = _chat()
        self.assertFalse(self._write(document, children=[]))
        self.assertNotIn("compaction", document["history"]["messages"]["a1"])


def _metadata(parent_compaction=None):
    return {
        "chat_id": "c",
        "message_id": "a2",
        "user_id": "u",
        "compaction": {
            "parent": {"id": "a1", "usage": None, "compaction": parent_compaction},
            "done": False,
        },
    }


@patch("open_webui.routers.openai.context_window_for", new=AsyncMock(return_value=1000))
class FitModelCallTest(unittest.IsolatedAsyncioTestCase):
    base = [{"role": "user", "content": "old " * 600}, {"role": "assistant", "content": "x"}, {"role": "user", "content": "now"}]

    async def test_under_the_window_nothing_happens(self):
        with patch.object(cc, "compact_chat", new=AsyncMock()) as compact:
            base, call = await cc.fit_model_call(
                MagicMock(), MagicMock(), {"id": "m"}, _metadata(), self.base, self.base, 900, cc.message_chars(self.base)
            )
        compact.assert_not_called()
        self.assertIs(call, self.base)

    async def test_over_the_window_compacts_once_per_turn(self):
        metadata = _metadata()
        done = {"status": "done", "summary": "S"}
        chat = MagicMock(chat={"chatNotes": []})
        with patch.object(cc, "compact_chat", new=AsyncMock(return_value=done)) as compact, patch.object(
            cc.Chats, "get_chat_by_id", return_value=chat
        ):
            base, call = await cc.fit_model_call(
                MagicMock(), MagicMock(), {"id": "m"}, metadata, self.base, self.base, 1200, cc.message_chars(self.base)
            )
            await cc.fit_model_call(
                MagicMock(), MagicMock(), {"id": "m"}, metadata, base, call, 1200, cc.message_chars(self.base)
            )
        compact.assert_awaited_once()
        self.assertEqual(compact.await_args.kwargs["message_id"], "a1")
        self.assertEqual(len(call), 1)
        self.assertIn("S", call[0]["content"])

    async def test_a_reply_already_compacted_is_not_compacted_again(self):
        with patch.object(cc, "compact_chat", new=AsyncMock()) as compact:
            await cc.fit_model_call(
                MagicMock(),
                MagicMock(),
                {"id": "m"},
                _metadata({"status": "done", "summary": "S"}),
                self.base,
                self.base,
                1200,
                cc.message_chars(self.base),
            )
        compact.assert_not_called()


class TurnEndTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, used, metadata=None):
        with patch.object(cc, "compact_chat", new=AsyncMock()) as compact:
            await cc.compact_at_turn_end(
                MagicMock(),
                MagicMock(),
                {"id": "m"},
                metadata or _metadata(),
                {"context_used": used, "context_window": 1000},
                {},
            )
        return compact

    async def test_over_ninety_percent_compacts_at_the_reply(self):
        compact = await self._run(901)
        self.assertEqual(compact.await_args.kwargs["message_id"], "a2")

    async def test_at_ninety_percent_or_under_does_nothing(self):
        (await self._run(900)).assert_not_called()

    async def test_not_after_a_compaction_this_turn(self):
        metadata = _metadata()
        metadata["compaction"]["done"] = True
        (await self._run(990, metadata)).assert_not_called()


class CompactChatTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, summarize, written=True):
        writes = []

        def set_compaction(chat_id, message_id, compaction, **kwargs):
            writes.append((compaction, kwargs))
            return written

        chat = MagicMock(chat=_chat(usage={"context_used": 900, "context_window": 1000}))
        with patch.object(cc.Chats, "get_chat_by_id", return_value=chat), patch.object(
            cc.Chats, "set_message_compaction", side_effect=set_compaction
        ), patch.object(cc, "_call_model", new=summarize), patch.object(cc, "_emit", new=AsyncMock()) as emit:
            result = await cc.compact_chat(
                MagicMock(), MagicMock(id="u"), chat_id="c", message_id="a1", model_id="m", emitter_meta={}
            )
        return result, writes, emit

    async def test_saves_running_then_the_summary(self):
        summarize = AsyncMock(return_value=("S", {"prompt_tokens": 500, "completion_tokens": 50}))
        result, writes, emit = await self._run(summarize)
        self.assertEqual(writes[0][0]["status"], "running")
        self.assertEqual(writes[0][1], {"bump_revision": False})
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["summary"], "S")
        self.assertIn("context_estimate", result)
        self.assertEqual(writes[1][1], {"children": ["u2"]})
        self.assertEqual(emit.await_args.args[3], result)

    async def test_failure_clears_the_running_state(self):
        result, writes, emit = await self._run(AsyncMock(side_effect=RuntimeError("down")))
        self.assertEqual(result, {"status": "failed"})
        self.assertIsNone(writes[-1][0])
        self.assertEqual(emit.await_args.args[3], {"status": "failed"})

    async def test_a_new_turn_meanwhile_cancels_it(self):
        summarize = AsyncMock(return_value=("S", {}))
        result, writes, _ = await self._run(summarize, written=False)
        self.assertEqual(result, {"status": "cancelled"})
        self.assertIsNone(writes[-1][0])

    async def test_a_slow_summary_times_out(self):
        async def slow(*_args):
            await asyncio.sleep(1)

        with patch.object(cc, "COMPACTION_TIMEOUT_S", 0.01):
            result, _, _ = await self._run(slow)
        self.assertEqual(result, {"status": "failed"})


class CompactChatThreadTest(unittest.IsolatedAsyncioTestCase):
    async def test_the_read_prompt_and_running_save_run_in_one_thread(self):
        threaded = []
        real_to_thread = asyncio.to_thread

        async def to_thread(fn, *args, **kwargs):
            threaded.append(getattr(fn, "__name__", repr(fn)))
            return await real_to_thread(fn, *args, **kwargs)

        chat = MagicMock(chat=_chat())
        summarize = AsyncMock(return_value=("S", {}))
        with patch.object(cc.asyncio, "to_thread", side_effect=to_thread), patch.object(
            cc.Chats, "get_chat_by_id", return_value=chat
        ), patch.object(cc.Chats, "set_message_compaction", return_value=True), patch.object(
            cc, "_call_model", new=summarize
        ), patch.object(cc, "_emit", new=AsyncMock()):
            result = await cc.compact_chat(
                MagicMock(), MagicMock(id="u"), chat_id="c", message_id="a1", model_id="m", emitter_meta={}
            )
        self.assertEqual(result["status"], "done")
        self.assertEqual(threaded[0], "_start_compaction")
        self.assertIn("first answer", summarize.await_args.args[3]["messages"][0]["content"])

    async def test_a_failed_start_writes_nothing_and_reports_failure(self):
        with patch.object(cc.Chats, "get_chat_by_id", side_effect=RuntimeError("db down")), patch.object(
            cc.Chats, "set_message_compaction"
        ) as write, patch.object(cc, "_emit", new=AsyncMock()) as emit:
            result = await cc.compact_chat(
                MagicMock(), MagicMock(id="u"), chat_id="c", message_id="a1", model_id="m", emitter_meta={}
            )
        self.assertEqual(result, {"status": "failed"})
        write.assert_not_called()
        self.assertEqual(emit.await_args.args[3], {"status": "failed"})
