from open_webui.utils.message_updates import (
    accumulate_usage,
    add_to_pending,
    apply_to_message,
    merge_files,
    upsert_by_id,
)


def test_usage_sums_tokens_and_costs_across_model_calls():
    first = {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.5, "model": "a",
             "completion_tokens_details": {"reasoning_tokens": 2}}
    second = {"prompt_tokens": 7, "completion_tokens": 3, "cost": 0.25, "model": "b",
              "completion_tokens_details": {"reasoning_tokens": 1}}
    total = accumulate_usage(accumulate_usage(None, first), second)
    assert total == {
        "prompt_tokens": 17,
        "completion_tokens": 8,
        "cost": 0.75,
        "model": "b",
        "completion_tokens_details": {"reasoning_tokens": 3},
    }
    assert first["prompt_tokens"] == 10  # inputs are not changed


def test_files_append_without_repeats():
    a = {"type": "image", "url": "/a.png"}
    b = {"type": "image", "url": "/b.png"}
    assert merge_files([a], [a, b]) == [a, b]


def test_code_runs_replace_by_id():
    running = {"id": "r1", "result": None}
    finished = {"id": "r1", "result": {"output": "ok"}}
    other = {"id": "r2"}
    assert upsert_by_id([running], [other, finished]) == [finished, other]


def test_a_batch_merges_into_the_stored_message():
    pending: dict = {}
    add_to_pending(pending, "status", {"description": "Searching", "done": False})
    add_to_pending(pending, "status", {"description": "Searched 3 sites", "done": True})
    add_to_pending(pending, "usage", {"total_tokens": 4})
    add_to_pending(pending, "usage", {"total_tokens": 6})
    add_to_pending(pending, "source", {"source": {"name": "new"}})
    add_to_pending(pending, "files", [{"url": "/b.png"}])
    stored = {
        "id": "a1",
        "content": "kept",
        "statusHistory": [{"description": "old 1"}, {"description": "old 2"}],
        "usage": {"total_tokens": 100},
        "sources": [{"source": {"name": "before the model ran"}}],
        "files": [{"url": "/a.png"}],
    }
    merged = apply_to_message(stored, pending)
    assert merged["content"] == "kept"
    assert merged["statusHistory"] == [{"description": "Searched 3 sites", "done": True}]
    assert merged["usage"] == {"total_tokens": 110}
    assert [s["source"]["name"] for s in merged["sources"]] == ["before the model ran", "new"]
    assert merged["files"] == [{"url": "/a.png"}, {"url": "/b.png"}]
