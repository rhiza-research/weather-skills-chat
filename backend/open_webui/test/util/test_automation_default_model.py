from open_webui.utils.automation_runner import _first_model_id


def test_first_model_id_prefers_org_default_then_app_default():
    assert _first_model_id("org-model, other", "app-model") == "org-model"
    assert _first_model_id(None, "app-model,other") == "app-model"
    assert _first_model_id("", None) is None
