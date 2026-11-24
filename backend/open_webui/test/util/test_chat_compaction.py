import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from open_webui.models.chats import Chats
from open_webui.utils import chat_compaction as cc
from open_webui.utils.chat_turns import messages_for_model


def _chat(**reply_fields):
    """u1 -> a1 (the reply compacted in most tests) -> u2 -> a2."""
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
                    "model": "weather-agent",
                    "usage": {"context_used": 900, "context_window": 1000},
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


class HelpersTest(unittest.TestCase):
    def test_context_after_removes_the_conversation_and_adds_the_summary(self):
        # The transcript is 3/4 of what the summary call was sent.
        result = cc.context_after(
            {"context_used": 180_000, "context_window": 200_000},
            {"prompt_tokens": 200_000, "completion_tokens": 2_000},
            75,
            100,
        )
        self.assertEqual(result, {"context_estimate": 32_000, "context_window": 200_000})

    def test_no_usage_gives_no_estimate(self):
        self.assertEqual(cc.context_after({}, {"prompt_tokens": 1, "completion_tokens": 1}, 1, 1), {})

    def test_running_goes_stale_after_the_timeout(self):
        now = time.time()
        self.assertTrue(cc.compaction_running({"status": "running", "started_at": now - 10}, now))
        self.assertFalse(
            cc.compaction_running(
                {"status": "running", "started_at": now - cc.COMPACTION_TIMEOUT_S - 1}, now
            )
        )
        self.assertFalse(cc.compaction_running({"status": "done"}, now))

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

    def test_oldest_tool_results_are_dropped_until_enough_is_gone(self):
        messages = [
            {"role": "user", "content": "go"},
            {"role": "tool", "content": "a" * 4000},
            {"role": "tool", "content": "b" * 4000},
        ]
        out = cc.drop_old_tool_results(messages, 2000)
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

    def test_final_reply_text_is_the_last_text_and_none_after_a_tool_call(self):
        self.assertEqual(cc.final_reply_text([{"role": "assistant", "content": "Done."}]), "Done.")
        self.assertIsNone(
            cc.final_reply_text([{"role": "assistant", "content": "", "tool_calls": [{"id": "t"}]}])
        )


class SetMessageCompactionTest(unittest.TestCase):
    def _write(self, document, **kwargs):
        def fake(_id, apply, **_kw):
            apply(document, None)
            return MagicMock(meta={"revision": 7}), "ok"

        with patch.object(Chats, "_write_locked_chat", side_effect=fake):
            return Chats.set_message_compaction("c", "a1", {"status": "done"}, **kwargs)

    def test_writes_while_the_replies_are_unchanged(self):
        document = _chat()
        self.assertEqual(self._write(document, children=["u2"]), 7)
        self.assertEqual(document["history"]["messages"]["a1"]["compaction"], {"status": "done"})

    def test_a_new_reply_wins_over_the_compaction(self):
        document = _chat()
        self.assertIsNone(self._write(document, children=[]))
        self.assertNotIn("compaction", document["history"]["messages"]["a1"])


class CompactTest(unittest.IsolatedAsyncioTestCase):
    """compact: one thread starts it, then the summary, then the save."""

    async def _run(
        self, chat_doc=None, fresh=None, resent=None, written=True, authorize=None, **kwargs
    ):
        writes = self.writes = []

        def set_compaction(chat_id, reply_id, compaction, **kw):
            writes.append((compaction, kw))
            return 5 if written else None

        fresh = fresh or AsyncMock(
            return_value={
                "choices": [{"message": {"content": "S"}}],
                "usage": {"prompt_tokens": 500, "completion_tokens": 50},
            }
        )
        chat = MagicMock(chat=chat_doc or _chat())
        with patch.object(cc.Chats, "get_chat_by_id", return_value=chat) as read, patch.object(
            cc.Chats, "set_message_compaction", side_effect=set_compaction
        ), patch("open_webui.utils.chat.generate_chat_completion", new=fresh), patch(
            "open_webui.utils.models.remember_catalog_model"
        ), patch(
            "open_webui.utils.chat.authorize_model_call", side_effect=authorize
        ), patch(
            "open_webui.routers.openai.resend_last_call", new=AsyncMock(return_value=resent)
        ) as resend, patch.object(cc, "_notify", new=AsyncMock()) as notify:
            try:
                result = await cc.compact(
                    MagicMock(), MagicMock(id="u"), "c", "a1", notify={}, **kwargs
                )
            except HTTPException as error:
                result = error
        self.resend = resend
        return result, writes, notify, fresh, read

    async def test_saves_running_then_the_summary_written_by_the_replys_model(self):
        result, writes, notify, fresh, read = await self._run()
        self.assertEqual(read.call_count, 1)
        self.assertEqual(writes[0][0]["status"], "running")
        self.assertEqual(writes[0][1], {"bump_revision": False})
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["summary"], "S")
        self.assertEqual(result["model"], "weather-agent")
        self.assertIn("context_estimate", result)
        self.assertEqual(writes[1][1], {"children": ["u2"]})
        # The page gets the revision too, so it drops older downloads.
        self.assertEqual(notify.await_args.args[3], {**result, "revision": 5})
        form = fresh.await_args.args[1]
        self.assertEqual(form["model"], "weather-agent")
        self.assertTrue(form["stream"])
        self.assertEqual(form["max_tokens"], cc.SUMMARY_MAX_TOKENS)
        prompt = form["messages"][0]["content"]
        self.assertIn("first answer", prompt)
        self.assertTrue(prompt.endswith(cc.SUMMARY_INSTRUCTIONS))

    async def test_a_streamed_summary_reports_each_step(self):
        chunks = [
            b": OPENROUTER PROCESSING\n\n",
            b'data: {"choices":[{"delta":{"content":"Sum"}}]}\n\n',
            b'data: {"choices":[{"delta":{"content":"mary"}}]}\n\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":500,"completion_tokens":40}}\n\ndata: [DONE]\n\n',
        ]

        async def body():
            for chunk in chunks:
                yield chunk

        closed = AsyncMock()
        stream = MagicMock(body_iterator=body(), background=closed)
        result, _, notify, _, _ = await self._run(fresh=AsyncMock(return_value=stream))
        self.assertEqual(result["summary"], "Summary")
        closed.assert_awaited_once()
        steps = [
            list(call.args[3]["steps"])
            for call in notify.await_args_list
            if call.args[3].get("status") == "running"
        ]
        self.assertEqual(steps, [["sending"], ["sending", "waiting"], ["sending", "waiting", "receiving"]])
        # The saved running state has no steps; only the events do.
        self.assertNotIn("steps", self.writes[0][0])

    async def test_a_warm_last_call_is_reused_instead_of_the_fresh_call(self):
        reply = {
            "choices": [{"message": {"content": "R"}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 10},
        }
        result, _, _, fresh, _ = await self._run(resent=(reply, 1000))
        self.assertEqual(result["summary"], "R")
        fresh.assert_not_called()
        # Its usage goes to the person compacting, as a task.
        usage_context = self.resend.await_args.args[5]
        self.assertEqual(usage_context["user_id"], "u")
        self.assertEqual(usage_context["source"], "task")

    async def test_a_cached_call_that_answers_with_a_tool_call_falls_back_to_fresh(self):
        reply = {"choices": [{"message": {"content": "", "tool_calls": [{"id": "t"}]}}]}
        result, _, _, fresh, _ = await self._run(resent=(reply, 1000))
        self.assertEqual(result["summary"], "S")
        fresh.assert_awaited_once()

    async def test_failure_clears_the_running_state(self):
        result, writes, notify, _, _ = await self._run(fresh=AsyncMock(side_effect=RuntimeError("down")))
        self.assertEqual(result, {"status": "failed"})
        self.assertIsNone(writes[-1][0])
        self.assertEqual(notify.await_args.args[3], {"status": "failed"})

    async def test_a_new_turn_meanwhile_cancels_it(self):
        result, writes, _, _, _ = await self._run(written=False)
        self.assertEqual(result, {"status": "cancelled"})
        self.assertIsNone(writes[-1][0])

    async def test_the_estimate_is_what_the_call_keeps_plus_the_summary(self):
        usage = {"context_used": 900, "context_window": 1000, "context_kept": 200}
        result, _, _, _, _ = await self._run(chat_doc=_chat(usage=usage))
        self.assertEqual(result["context_estimate"], 250)
        self.assertEqual(result["context_window"], 1000)

    async def test_a_slow_summary_times_out(self):
        async def slow(*_args):
            await asyncio.sleep(1)

        with patch.object(cc, "COMPACTION_TIMEOUT_S", 0.01):
            result, _, _, _, _ = await self._run(fresh=slow)
        self.assertEqual(result, {"status": "failed"})

    async def test_only_a_saved_compaction_stops_the_cache_keepalive(self):
        for written, stops in ((True, 1), (False, 0)):
            with patch.object(cc.cache_keepalive, "restart") as restart:
                await self._run(written=written)
            self.assertEqual(restart.call_count, stops)
            if stops:
                self.assertEqual(restart.call_args.args[:2], ("c", None))

    async def test_a_stopped_turn_clears_the_running_state(self):
        started = asyncio.Event()

        async def slow(*_args):
            started.set()
            await asyncio.sleep(60)

        task = asyncio.create_task(self._run(fresh=slow))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.writes[0][0]["status"], "running")
        self.assertIsNone(self.writes[-1][0])

    async def test_a_spending_limit_or_model_access_refuses_before_anything_starts(self):
        for error in (HTTPException(429, "limit"), Exception("Model not found")):
            result, writes, notify, fresh, _ = await self._run(authorize=error, check_reply=True)
            self.assertIn(result.status_code, (429, 403))
            self.assertEqual(writes, [])
            notify.assert_not_called()
            fresh.assert_not_called()

    async def test_an_automatic_compaction_that_is_refused_just_fails(self):
        result, writes, _, fresh, _ = await self._run(authorize=HTTPException(429, "limit"))
        self.assertEqual(result, {"status": "failed"})
        self.assertEqual(writes, [])
        fresh.assert_not_called()

    async def test_checked_replies_are_refused_before_anything_is_saved_or_sent(self):
        cases = [
            (_chat(done=False), 409),
            (_chat(compaction={"status": "done", "summary": "S"}), 409),
            (_chat(compaction={"status": "running", "started_at": time.time()}), 409),
            (_chat(model=None), 400),
        ]
        for doc, code in cases:
            result, writes, notify, _, _ = await self._run(doc, check_reply=True)
            self.assertEqual(getattr(result, "status_code", None), code)
            self.assertEqual(writes, [])
            notify.assert_not_called()


def _parent(**fields):
    return {"id": "a1", "usage": {"context_used": 900}, "compaction": None, **fields}


@patch("open_webui.routers.openai.context_window_for", new=AsyncMock(return_value=1000))
class ContextBudgetTest(unittest.IsolatedAsyncioTestCase):
    # The reply before this turn ended at 900 tokens; the new message adds "now".
    base = [
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "x"},
        {"role": "user", "content": "now"},
    ]
    done = {"status": "done", "summary": "S"}

    async def _fit(self, context_budget, call, compact):
        chat = MagicMock(chat={"chatNotes": []})
        with patch.object(cc, "compact", new=compact), patch.object(cc.Chats, "get_chat_by_id", return_value=chat):
            return await context_budget.fit(MagicMock(), MagicMock(), {"id": "m"}, {}, self.base, call)

    async def test_a_call_that_fits_is_sent_as_is(self):
        compact = AsyncMock()
        _, call = await self._fit(cc.ContextBudget("c", "a2", _parent()), self.base, compact)
        compact.assert_not_called()
        self.assertIs(call, self.base)

    async def test_over_the_window_compacts_the_previous_reply_once_per_turn(self):
        context_budget = cc.ContextBudget("c", "a2", _parent(usage={"context_used": 1200}))
        compact = AsyncMock(return_value=self.done)
        _, call = await self._fit(context_budget, self.base, compact)
        context_budget.record({"prompt_tokens": 1200})
        await self._fit(context_budget, call, compact)
        compact.assert_awaited_once()
        self.assertEqual(compact.await_args.args[3], "a1")
        self.assertEqual(len(call), 1)
        self.assertIn("S", call[0]["content"])

    async def test_a_previous_reply_already_compacted_is_not_compacted_again(self):
        context_budget = cc.ContextBudget("c", "a2", _parent(usage={"context_used": 1200}, compaction=self.done))
        compact = AsyncMock()
        await self._fit(context_budget, self.base, compact)
        compact.assert_not_called()

    async def test_without_a_saved_turn_it_only_drops_old_tool_results(self):
        call = [*self.base, {"role": "tool", "content": "z" * 8000}]
        compact = AsyncMock()
        _, fitted = await self._fit(cc.ContextBudget(), call, compact)
        compact.assert_not_called()
        self.assertEqual(fitted[-1]["content"], cc.TOOL_RESULT_REMOVED)

    async def test_record_counts_the_prompt_tokens_a_compaction_keeps(self):
        context_budget = cc.ContextBudget("c", "a2", _parent())
        call = [{"role": "system", "content": "s" * 100}, *self.base]
        tools = [{"name": "t" * 86}]  # 100 characters as JSON
        await context_budget.fit(MagicMock(), MagicMock(), {}, {}, call, call, tools)
        usage = {"prompt_tokens": 2070}
        context_budget.record(usage)
        # 200 of the call's 207 characters are system message and tools.
        self.assertEqual(usage["context_kept"], 2000)

    async def test_finish_compacts_the_reply_over_ninety_percent(self):
        for used, expected in ((901, 1), (900, 0)):
            context_budget = cc.ContextBudget("c", "a2", _parent())
            context_budget.record({"context_used": used, "context_window": 1000})
            with patch.object(cc, "compact", new=AsyncMock()) as compact:
                await context_budget.finish(MagicMock(), MagicMock(), {}, {})
            self.assertEqual(compact.await_count, expected)
            if expected:
                self.assertEqual(compact.await_args.args[3], "a2")

    async def test_announce_tells_the_page_only_when_finish_will_compact(self):
        for used, expected in ((901, 1), (900, 0)):
            context_budget = cc.ContextBudget("c", "a2", _parent())
            context_budget.record({"context_used": used, "context_window": 1000})
            with patch.object(cc, "_notify", new=AsyncMock()) as notify:
                await context_budget.announce({})
            self.assertEqual(notify.await_count, expected)
            if expected:
                self.assertEqual(notify.await_args.args[2], "a2")
                self.assertEqual(notify.await_args.args[3]["status"], "running")

    async def test_finish_does_nothing_after_a_compaction_this_turn(self):
        context_budget = cc.ContextBudget("c", "a2", _parent())
        context_budget.compacted = True
        context_budget.record({"context_used": 990, "context_window": 1000})
        with patch.object(cc, "compact", new=AsyncMock()) as compact:
            await context_budget.finish(MagicMock(), MagicMock(), {}, {})
        compact.assert_not_called()
