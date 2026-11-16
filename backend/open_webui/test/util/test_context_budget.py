"""Tests for fitting the conversation under the model's token budget."""

from __future__ import annotations

import unittest

from unittest.mock import patch

from open_webui.utils import context_budget
from open_webui.utils.context_budget import (
    CLEARED_RESULT,
    FALLBACK_CONTEXT_WINDOW,
    IMAGE_TOKENS,
    KEEP_RECENT_ROUNDS,
    compact_messages,
    estimate_tokens,
    token_budget,
)

BIG = "x" * 3_000  # 1,000 tokens


def tool_round(call_id: str, result: str = BIG) -> list[dict]:
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "run", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": call_id, "content": result},
    ]


def chat(turns: int, rounds_per_turn: int, user_text: str = "hi") -> list[dict]:
    messages = [{"role": "system", "content": "You are the weather agent."}]
    for t in range(turns):
        messages.append({"role": "user", "content": user_text})
        for r in range(rounds_per_turn):
            messages += tool_round(f"t{t}r{r}")
        messages.append({"role": "assistant", "content": "done"})
    return messages


def cleared_ids(messages: list[dict]) -> list[str]:
    return [
        m["tool_call_id"]
        for m in messages
        if m.get("role") == "tool" and m["content"] == CLEARED_RESULT
    ]


def assert_pairs_intact(test: unittest.TestCase, messages: list[dict]) -> None:
    calls = {
        c["id"] for m in messages for c in (m.get("tool_calls") or [])
    }
    results = {m["tool_call_id"] for m in messages if m.get("role") == "tool"}
    test.assertEqual(calls, results)


class CompactMessagesTest(unittest.TestCase):
    def test_under_budget_is_untouched(self):
        messages = chat(turns=2, rounds_per_turn=2)
        out, changed = compact_messages(messages, budget=1_000_000)
        self.assertFalse(changed)
        self.assertIs(out, messages)

    def test_zero_budget_turns_it_off(self):
        messages = chat(turns=20, rounds_per_turn=5)
        out, changed = compact_messages(messages, budget=0)
        self.assertFalse(changed)
        self.assertIs(out, messages)

    def test_clears_oldest_results_first_and_only_as_many_as_needed(self):
        messages = chat(turns=10, rounds_per_turn=3)  # ~30k tokens
        out, changed = compact_messages(messages, budget=24_000)

        self.assertTrue(changed)
        self.assertLessEqual(estimate_tokens(out), 24_000)
        cleared = cleared_ids(out)
        self.assertTrue(cleared)
        self.assertEqual(cleared[0], "t0r0")
        # Not everything: later results survive.
        self.assertIn("t9r2", [m.get("tool_call_id") for m in out])
        self.assertNotIn("t9r2", cleared)
        # Clearing alone was enough, so no turn was dropped.
        self.assertEqual(len(out), len(messages))
        assert_pairs_intact(self, out)

    def test_does_not_change_the_callers_messages(self):
        messages = chat(turns=10, rounds_per_turn=3)
        compact_messages(messages, budget=24_000)
        self.assertEqual(cleared_ids(messages), [])

    def test_recent_rounds_are_never_cleared(self):
        # One long reply: every round is in the last turn.
        messages = chat(turns=1, rounds_per_turn=20)
        out, _ = compact_messages(messages, budget=5_000)

        recent = [f"t0r{r}" for r in range(20 - KEEP_RECENT_ROUNDS, 20)]
        self.assertFalse(set(recent) & set(cleared_ids(out)))
        self.assertIn("t0r0", cleared_ids(out))

    def test_drops_oldest_turns_when_clearing_is_not_enough(self):
        # Big user messages that clearing tool output cannot shrink.
        messages = chat(turns=10, rounds_per_turn=1, user_text="y" * 30_000)
        out, changed = compact_messages(messages, budget=60_000)

        self.assertTrue(changed)
        self.assertLessEqual(estimate_tokens(out), 60_000)
        self.assertEqual(out[0]["role"], "system")
        self.assertEqual(out[1]["role"], "user")
        self.assertLess(len(out), len(messages))
        ids = [m.get("tool_call_id") for m in out if m.get("role") == "tool"]
        self.assertNotIn("t0r0", ids)
        self.assertIn("t9r0", ids)
        assert_pairs_intact(self, out)

    def test_last_turn_is_never_dropped(self):
        messages = chat(turns=1, rounds_per_turn=1, user_text="y" * 300_000)
        out, _ = compact_messages(messages, budget=10_000)
        self.assertEqual(out[-1], messages[-1])
        self.assertEqual(out[1], messages[1])

    def test_trim_point_holds_while_the_chat_grows(self):
        # The provider's prompt cache only hits if two sends in a row clear
        # the same results.
        messages = chat(turns=30, rounds_per_turn=3)  # ~90k tokens
        first, _ = compact_messages(messages, budget=80_000)
        grown = messages + tool_round("next") + [
            {"role": "assistant", "content": "more"}
        ]
        second, _ = compact_messages(grown, budget=80_000)
        self.assertEqual(cleared_ids(first), cleared_ids(second))
        self.assertEqual(first, second[: len(first)])

    def test_image_counts_as_a_fixed_cost(self):
        image = {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + "A" * 3_000_000},
        }
        self.assertEqual(estimate_tokens(image), IMAGE_TOKENS)


class TokenBudgetTest(unittest.TestCase):
    def test_budget_is_a_share_of_the_providers_window(self):
        self.assertEqual(token_budget({"context_length": 1_000_000}), 850_000)
        self.assertEqual(token_budget({"context_window": 200_000}), 170_000)

    def test_an_unlisted_model_gets_the_fallback_window(self):
        expected = int(FALLBACK_CONTEXT_WINDOW * 0.85)
        self.assertEqual(token_budget(None), expected)
        self.assertEqual(token_budget({"context_length": None}), expected)

    def test_zero_percent_turns_it_off(self):
        with patch.object(context_budget, "MODEL_CONTEXT_BUDGET_PERCENT", 0):
            self.assertEqual(token_budget({"context_length": 1_000_000}), 0)


if __name__ == "__main__":
    unittest.main()
