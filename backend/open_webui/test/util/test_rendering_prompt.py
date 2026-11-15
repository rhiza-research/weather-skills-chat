from open_webui.utils.payload import append_system_prompt

DEFAULT = (
    "Responses will be interpreted as github markdown. Please use proper escape "
    "sequences if you would like to use markdown-specific characters but not "
    "render them as markdown"
)


def test_append_system_prompt_adds_system_message():
    form_data = {"messages": [{"role": "user", "content": "Hello"}]}
    append_system_prompt(form_data, DEFAULT)
    assert form_data["messages"][0]["role"] == "system"
    assert "github markdown" in form_data["messages"][0]["content"]
    assert form_data["messages"][1]["role"] == "user"


def test_append_system_prompt_skips_when_already_present():
    form_data = {
        "messages": [
            {"role": "system", "content": DEFAULT},
            {"role": "user", "content": "Hello"},
        ]
    }
    append_system_prompt(form_data, DEFAULT)
    assert form_data["messages"][0]["content"] == DEFAULT


def test_append_system_prompt_noop_when_empty():
    form_data = {"messages": [{"role": "user", "content": "Hello"}]}
    append_system_prompt(form_data, "")
    assert len(form_data["messages"]) == 1
    assert form_data["messages"][0]["role"] == "user"


def test_append_system_prompt_appends_to_existing_system():
    form_data = {
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
        ]
    }
    append_system_prompt(form_data, DEFAULT)
    content = form_data["messages"][0]["content"]
    assert content.startswith("You are a helpful assistant.")
    assert content.endswith(DEFAULT)
