from open_webui.utils.payload import apply_model_params_to_body_openai


def test_provider_is_sent_with_the_request():
    params = {"provider": {"quantizations": ["fp8"], "allow_fallbacks": False}}
    form_data = {"model": "z-ai/glm-5.3-flash", "messages": []}
    apply_model_params_to_body_openai(params, form_data)
    assert form_data["provider"] == {"quantizations": ["fp8"], "allow_fallbacks": False}


def test_no_provider_key_without_the_param():
    form_data = {"model": "z-ai/glm-5.3-flash", "messages": []}
    apply_model_params_to_body_openai({"temperature": 0.2}, form_data)
    assert "provider" not in form_data
