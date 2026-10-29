"""The base model list sent to the browser carries only what the model editor reads."""

from open_webui.utils.models import listed_base_model

OPENROUTER_RECORD = {
    "id": "anthropic/claude-opus-4",
    "name": "Anthropic: Claude Opus 4",
    "description": "A long description of the model. " * 40,
    "pricing": {"prompt": "0.000015", "completion": "0.000075"},
    "architecture": {"modality": "text+image->text"},
    "context_length": 200000,
}


def _merged(record, prefix=None, url_idx=0, connection="openrouter.ai"):
    """A model as openai.get_all_models merges it."""
    model_id = f"{prefix}.{record['id']}" if prefix else record["id"]
    return {
        **record,
        "id": model_id,
        "name": record.get("name", model_id),
        "owned_by": "openai",
        "openai": record,
        "urlIdx": url_idx,
        "connection_name": connection,
        "upstream_id": record["id"],
    }


def test_provider_record_stays_on_the_server():
    listed = listed_base_model(_merged(OPENROUTER_RECORD))

    assert listed == {
        "id": "anthropic/claude-opus-4",
        "name": "Anthropic: Claude Opus 4",
        "owned_by": "openai",
        "urlIdx": 0,
        "connection_name": "openrouter.ai",
    }


def test_upstream_id_is_sent_only_when_a_prefix_changes_the_id():
    listed = listed_base_model(_merged(OPENROUTER_RECORD, prefix="open-router-"))

    assert listed["id"] == "open-router-.anthropic/claude-opus-4"
    assert listed["upstream_id"] == "anthropic/claude-opus-4"


def test_a_model_from_a_function_keeps_its_id_and_name():
    pipe = {
        "id": "my_pipe",
        "name": "My Pipe",
        "object": "model",
        "created": 1,
        "owned_by": "openai",
        "pipe": {"type": "pipe"},
    }

    assert listed_base_model(pipe) == {
        "id": "my_pipe",
        "name": "My Pipe",
        "owned_by": "openai",
    }
