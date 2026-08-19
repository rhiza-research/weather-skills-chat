from open_webui.utils.payload import HEADLESS_SYSTEM_CONTEXT, inject_headless_context


def test_inject_headless_context_adds_system_message():
    form_data = {"messages": [{"role": "user", "content": "Run the report."}]}
    inject_headless_context(form_data)
    assert form_data["messages"][0]["role"] == "system"
    assert "scheduled automation" in form_data["messages"][0]["content"]
    assert form_data["messages"][1]["role"] == "user"


def test_inject_headless_context_skips_when_already_present():
    form_data = {
        "messages": [
            {"role": "system", "content": HEADLESS_SYSTEM_CONTEXT},
            {"role": "user", "content": "Run the report."},
        ]
    }
    inject_headless_context(form_data)
    assert form_data["messages"][0]["content"] == HEADLESS_SYSTEM_CONTEXT
