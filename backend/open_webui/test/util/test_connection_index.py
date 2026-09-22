"""Chat send picks a connection from the base model id, without a model list."""

from types import SimpleNamespace

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
