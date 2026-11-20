"""The system message must come out the same on every model call, so the prompt cache can reuse it."""

from open_webui.utils.payload import (
    FEEDBACK_LINK_PROMPT,
    apply_model_system_prompt_to_body,
    append_system_prompt,
)

RENDERING = "Responses will be interpreted as github markdown."
MODEL_PROMPT = "You are an agent helping forecasters. The current date is 2026-11-14."
HINTS = "Tools/skills enabled for this chat: `plot`."


def _middleware_order(model_first: bool) -> str:
    """Build a system message the way the chat middleware does, then apply the model prompt again
    the way openai.generate_chat_completion does on every model call."""
    form_data = {"messages": [{"role": "system", "content": HINTS}, {"role": "user", "content": "Hi"}]}
    params = {"system": MODEL_PROMPT}
    if model_first:
        form_data = apply_model_system_prompt_to_body(params, form_data)
    form_data = append_system_prompt(form_data, RENDERING)
    form_data = append_system_prompt(form_data, FEEDBACK_LINK_PROMPT)
    form_data = apply_model_system_prompt_to_body(params, form_data)  # the router's call
    form_data = apply_model_system_prompt_to_body(params, form_data)  # a later tool-loop round
    return form_data["messages"][0]["content"]


def test_model_prompt_is_not_duplicated():
    content = _middleware_order(model_first=True)
    assert content.count(MODEL_PROMPT) == 1
    assert content.count(RENDERING) == 1


def test_order_does_not_depend_on_which_step_adds_the_model_prompt():
    assert _middleware_order(model_first=True) == _middleware_order(model_first=False)


def test_model_prompt_leads_and_universal_prompts_follow():
    content = _middleware_order(model_first=True)
    assert content.startswith(MODEL_PROMPT)
    assert content.index(HINTS) < content.index(RENDERING) < content.index(FEEDBACK_LINK_PROMPT.strip()[:40])
