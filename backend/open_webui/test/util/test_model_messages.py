"""Tests for model-facing message compaction and system-prompt idempotency."""

from __future__ import annotations

import json
import unittest
from datetime import datetime

from open_webui.utils.misc import add_or_update_system_message
from open_webui.utils.model_messages import (
    compact_tool_result_for_model,
    serialize_content_blocks_for_model,
    strip_message_details_for_tasks,
)
from open_webui.routers.openai import (
    enable_openrouter_prompt_caching,
    _is_openrouter_anthropic_model,
)


class SystemMessageIdempotencyTest(unittest.TestCase):
    def test_repeated_apply_does_not_stack(self):
        system = "You are the weather agent."
        messages = [{"role": "user", "content": "hi"}]
        for _ in range(5):
            add_or_update_system_message(system, messages)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[0]["content"].count(system), 1)

    def test_client_then_server_same_prompt_stays_once(self):
        system = "You are the weather agent."
        messages = [{"role": "system", "content": system}, {"role": "user", "content": "hi"}]
        add_or_update_system_message(system, messages)
        self.assertEqual(messages[0]["content"], system)

    def test_different_prefix_still_prepends_once(self):
        messages = [{"role": "system", "content": "client hint"}, {"role": "user", "content": "hi"}]
        add_or_update_system_message("model system", messages)
        self.assertEqual(messages[0]["content"], "model system\nclient hint")
        add_or_update_system_message("model system", messages)
        self.assertEqual(messages[0]["content"], "model system\nclient hint")


class CompactToolResultTest(unittest.TestCase):
    def test_success_drops_stderr_and_infra(self):
        payload = {
            "ok": True,
            "exit_code": 0,
            "script": "fetch.py",
            "argv": ["--out", "x.zarr"],
            "stdout": "wrote x.zarr",
            "stderr": "Downloading cpython...\nInstalled packages",
            "cwd": "/tmp/sandbox",
            "sandlock": True,
            "landlock_backend": "sandlock",
        }
        out = json.loads(compact_tool_result_for_model(json.dumps(payload, indent=2)))
        self.assertNotIn("stderr", out)
        self.assertNotIn("cwd", out)
        self.assertNotIn("sandlock", out)
        self.assertEqual(out["stdout"], "wrote x.zarr")
        self.assertTrue(out["ok"])

    def test_failure_keeps_stderr(self):
        payload = {
            "ok": False,
            "exit_code": 1,
            "stdout": "",
            "stderr": "Traceback: boom",
            "cwd": "/tmp",
            "sandlock": True,
        }
        out = json.loads(compact_tool_result_for_model(json.dumps(payload)))
        self.assertEqual(out["stderr"], "Traceback: boom")
        self.assertNotIn("cwd", out)

    def test_truncates_long_stdout(self):
        payload = {"ok": True, "exit_code": 0, "stdout": "x" * 50_000}
        out = json.loads(compact_tool_result_for_model(json.dumps(payload)))
        self.assertIn("truncated", out["stdout"])
        self.assertLess(len(out["stdout"]), 20_000)


class StripTaskHistoryTest(unittest.TestCase):
    def test_strips_tool_calls_and_reasoning(self):
        messages = [
            {"role": "user", "content": "Fetch Kenya precip"},
            {
                "role": "assistant",
                "content": (
                    '<details type="reasoning" done="true"><summary>Thinking</summary>'
                    "secret thoughts</details>\n"
                    '<details type="tool_calls" done="true" name="ecmwf_fetch" '
                    'result="{&quot;ok&quot;: true, &quot;stderr&quot;: &quot;uv noise&quot;}">'
                    "<summary>Tool</summary></details>\n\nHere is the forecast."
                ),
            },
        ]
        cleaned = strip_message_details_for_tasks(messages)
        self.assertEqual(cleaned[0]["content"], "Fetch Kenya precip")
        self.assertEqual(cleaned[1]["content"], "Here is the forecast.")
        self.assertNotIn("tool_calls", cleaned[1]["content"])
        self.assertNotIn("uv noise", cleaned[1]["content"])
        # Original unchanged
        self.assertIn("tool_calls", messages[1]["content"])


class SerializeForModelTest(unittest.TestCase):
    def test_no_details_html(self):
        blocks = [
            {"type": "reasoning", "content": "I will call a tool"},
            {"type": "text", "content": "Done."},
        ]
        text = serialize_content_blocks_for_model(blocks)
        self.assertEqual(text, "I will call a tool\nDone.")
        self.assertNotIn("<details", text)


class OpenRouterCacheTest(unittest.TestCase):
    def test_anthropic_detection(self):
        self.assertTrue(_is_openrouter_anthropic_model("anthropic/claude-sonnet-4"))
        self.assertFalse(_is_openrouter_anthropic_model("openai/gpt-4o"))

    def test_injects_cache_control_session_and_breakpoints(self):
        payload = {
            "model": "anthropic/claude-sonnet-4",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "hi"},
            ],
            "tools": [
                {"type": "function", "function": {"name": "a", "parameters": {}}},
                {"type": "function", "function": {"name": "b", "parameters": {}}},
            ],
        }
        original_tools = payload["tools"]
        out = enable_openrouter_prompt_caching(
            "https://openrouter.ai/api/v1",
            payload,
            {"chat_id": "abc-123", "user_id": "user-1"},
        )
        self.assertEqual(out["cache_control"], {"type": "ephemeral"})
        self.assertEqual(out["session_id"], "abc-123")
        self.assertTrue(out["prompt_cache_key"].startswith("user-1:"))
        # System becomes multipart with cache_control
        sys_content = out["messages"][0]["content"]
        self.assertIsInstance(sys_content, list)
        self.assertEqual(sys_content[0]["text"], "You are helpful.")
        self.assertEqual(sys_content[0]["cache_control"], {"type": "ephemeral"})
        # Last tool marked; shared list not mutated
        self.assertEqual(out["tools"][-1]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", original_tools[-1])
        self.assertNotIn("cache_control", out["tools"][0])

    def test_skips_non_openrouter(self):
        payload = {"model": "anthropic/claude-sonnet-4", "messages": []}
        out = enable_openrouter_prompt_caching(
            "https://api.anthropic.com/v1",
            payload,
            {"chat_id": "abc-123", "user_id": "user-1"},
        )
        self.assertNotIn("cache_control", out)
        self.assertNotIn("session_id", out)
        self.assertNotIn("prompt_cache_key", out)

    def test_openai_sticky_prompt_cache_key_from_user(self):
        payload = {
            "model": "openai/gpt-4o",
            "messages": [{"role": "system", "content": "sys"}],
            "tools": [{"type": "function", "function": {"name": "a"}}],
        }
        user = type("U", (), {"id": "user-42"})()
        out = enable_openrouter_prompt_caching(
            "https://openrouter.ai/api/v1",
            payload,
            {"chat_id": "chat-A"},
            user,
        )
        self.assertNotIn("cache_control", out)
        self.assertEqual(out["session_id"], "chat-A")
        self.assertEqual(
            out["prompt_cache_key"],
            f"user-42:{datetime.now().strftime('%Y-%m-%d')}",
        )
        # Same user, different chat → same cache key
        out2 = enable_openrouter_prompt_caching(
            "https://openrouter.ai/api/v1",
            {
                "model": "openai/gpt-4o",
                "messages": [{"role": "system", "content": "sys"}],
            },
            {"chat_id": "chat-B"},
            user,
        )
        self.assertEqual(out["prompt_cache_key"], out2["prompt_cache_key"])
        self.assertNotEqual(out["session_id"], out2["session_id"])


if __name__ == "__main__":
    unittest.main()
