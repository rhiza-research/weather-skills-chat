"""Each usage report carries how full the model's context was on that call."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from open_webui.routers import openai as openai_router
from open_webui.utils.message_updates import accumulate_usage
from open_webui.utils.middleware import context_usage

MODELS = {
    "data": [
        {"id": "anthropic/claude-opus-4", "context_length": 200000},
        {"id": "no-length/model"},
    ]
}


def _usage(model_id, usage, models=MODELS, base_model_id=None):
    openai_router._context_windows.update(at=float("-inf"), by_id={})
    row = SimpleNamespace(base_model_id=base_model_id) if base_model_id else None
    with patch.object(
        openai_router, "get_all_models", AsyncMock(return_value=models)
    ), patch.object(openai_router.Models, "get_model_by_id", return_value=row):
        return asyncio.run(context_usage(None, None, {"id": model_id}, usage))


def test_reports_prompt_tokens_against_the_window():
    assert _usage("anthropic/claude-opus-4", {"prompt_tokens": 50000}) == {
        "context_used": 50000,
        "context_window": 200000,
    }


def test_wrapper_model_uses_its_base_model_window():
    out = _usage("my-model", {"prompt_tokens": 10}, base_model_id="anthropic/claude-opus-4")
    assert out["context_window"] == 200000


def test_nothing_when_the_window_is_unknown():
    assert _usage("no-length/model", {"prompt_tokens": 10}) == {}
    assert _usage("anthropic/claude-opus-4", {"completion_tokens": 10}) == {}


def test_tool_loop_keeps_the_last_call_not_the_sum():
    first = {"prompt_tokens": 100, "context_used": 100, "context_window": 200000}
    second = {"prompt_tokens": 150, "context_used": 150, "context_window": 200000}
    total = accumulate_usage(accumulate_usage(None, first), second)
    assert total["prompt_tokens"] == 250
    assert total["context_used"] == 150
