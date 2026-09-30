"""Chat send picks a connection from the base model id, without a model list."""

from types import SimpleNamespace
from unittest.mock import patch

from open_webui.routers import openai as openai_router
from open_webui.routers.openai import connection_index_for_model


def _request(urls, configs=None):
    config = SimpleNamespace(
        OPENAI_API_BASE_URLS=urls,
        OPENAI_API_CONFIGS=configs or {},
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(config=config)))


def test_unrestricted_connection_accepts_base_model_id():
    request = _request(["https://openrouter.ai/api/v1"])
    assert connection_index_for_model(request, "openai/gpt-4o") == 0


def test_allowlist_skips_other_connections():
    request = _request(
        ["https://openrouter.ai/api/v1", "https://api.openai.com/v1"],
        {
            "0": {"enable": True, "model_ids": []},
            "1": {"enable": True, "model_ids": ["gpt-4o"]},
        },
    )
    assert connection_index_for_model(request, "openai/gpt-4o") == 0
    assert connection_index_for_model(request, "gpt-4o") == 1


def test_disabled_connection_is_skipped():
    request = _request(
        ["https://openrouter.ai/api/v1", "https://other.example/v1"],
        {"0": {"enable": False}, "1": {"enable": True}},
    )
    assert connection_index_for_model(request, "openai/gpt-4o") == 1


def test_prefix_is_stripped_before_allowlist_match():
    request = _request(
        ["https://openrouter.ai/api/v1"],
        {"0": {"prefix_id": "or", "model_ids": ["openai/gpt-4o"]}},
    )
    assert connection_index_for_model(request, "or.openai/gpt-4o") == 0


def test_tracing_style_follows_wrapper_to_base_connection():
    request = _request(
        ["https://openrouter.ai/api/v1", "https://api.openai.com/v1"],
        {
            "0": {"model_ids": ["openai/gpt-4o"], "model_call_tracing": "openrouter"},
            "1": {"model_ids": ["gpt-4o"]},
        },
    )
    wrapper = SimpleNamespace(base_model_id="openai/gpt-4o")
    with patch.object(openai_router, "tracing_enabled", return_value=True), patch.object(
        openai_router.Models, "get_model_by_id", return_value=wrapper
    ):
        assert (
            openai_router.model_call_tracing_style_for_model(request, "weather-agent")
            == "openrouter"
        )
    with patch.object(openai_router, "tracing_enabled", return_value=True), patch.object(
        openai_router.Models, "get_model_by_id", return_value=None
    ):
        assert openai_router.model_call_tracing_style_for_model(request, "gpt-4o") == "app"


def test_tracing_style_skips_model_lookup_when_no_connection_opts_in():
    request = _request(["https://openrouter.ai/api/v1"], {"0": {"enable": True}})
    with patch.object(openai_router, "tracing_enabled", return_value=True), patch.object(
        openai_router.Models, "get_model_by_id"
    ) as lookup:
        assert openai_router.model_call_tracing_style_for_model(request, "m") == "app"
        lookup.assert_not_called()


def test_api_config_for_index_tolerates_missing_configs():
    request = _request(["https://openrouter.ai/api/v1"])
    request.app.state.config.OPENAI_API_CONFIGS = None
    assert openai_router.api_config_for_index(request, 0) == {}


def test_api_config_for_index_tolerates_none_value():
    request = _request(["https://openrouter.ai/api/v1"], {"0": None})
    assert openai_router.api_config_for_index(request, 0) == {}


def test_api_config_for_index_legacy_url_key():
    url = "https://openrouter.ai/api/v1"
    request = _request([url], {url: {"prefix_id": "or"}})
    assert openai_router.api_config_for_index(request, 0) == {"prefix_id": "or"}
    request = _request([url], {url: None})
    assert openai_router.api_config_for_index(request, 0) == {}


def test_api_config_for_index_prefers_index_key():
    url = "https://openrouter.ai/api/v1"
    request = _request([url], {"0": {"prefix_id": "a"}, url: {"prefix_id": "b"}})
    assert openai_router.api_config_for_index(request, 0) == {"prefix_id": "a"}


def test_provider_trace_style_needs_carried_and_configured_to_match():
    openrouter = {"model_call_tracing": "openrouter"}
    style = openai_router.provider_trace_style
    assert style(openrouter, {}) == "app"
    assert style({}, openrouter) == "app"
    assert style({"model_call_tracing": "app"}, openrouter) == "app"
    assert style(None, openrouter) == "app"
    assert style({"model_call_tracing": "made-up"}, {"model_call_tracing": "made-up"}) == "app"
    assert style(openrouter, openrouter) == "openrouter"


def test_tracing_style_is_app_when_tracing_off():
    request = _request(
        ["https://openrouter.ai/api/v1"], {"0": {"model_call_tracing": "openrouter"}}
    )
    with patch.object(openai_router, "tracing_enabled", return_value=False):
        assert openai_router.model_call_tracing_style_for_model(request, "m") == "app"
