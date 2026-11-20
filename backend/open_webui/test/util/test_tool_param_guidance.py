"""Parameters repeated on every tool keep short descriptions; the system prompt explains them once, in full."""

import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from open_webui.utils.skill_runtime import DEFAULT_TIMEOUT_SEC, MAX_TIMEOUT_SEC
from open_webui.utils.skills import generate_tool_content, skill_argument_guidance
from open_webui.utils.tool_parallel import (
    ACTIVITY_SCHEMA,
    DEPENDS_ON_SCHEMA,
    DISPLAY_SCHEMA,
    TOOL_CALL_GUIDANCE,
)

# Each of these is sent once per tool, on every model call.
SHORT = 70


def _skill_param_docs() -> dict:
    source = generate_tool_content(
        method_name="run_x", skill_name="x", description="d", usage="u", skill_dir=Path("/tmp"), version="1"
    )
    namespace: dict = {}
    exec(source, namespace)
    doc = namespace["Tools"].run_x.__doc__
    return dict(re.findall(r":param (\w+): (.*)", doc))


def test_reserved_parameter_descriptions_are_short():
    for schema in (DEPENDS_ON_SCHEMA, DISPLAY_SCHEMA, ACTIVITY_SCHEMA):
        assert len(schema["description"]) <= SHORT, schema["description"]


def test_skill_parameter_descriptions_are_short():
    docs = _skill_param_docs()
    for name in ("argv", "env_secrets", "timeout"):
        assert len(docs[name]) <= SHORT, docs[name]


def test_system_prompt_explains_depends_on_display_and_activity():
    text = TOOL_CALL_GUIDANCE
    assert "`depends_on`" in text and "tool_call id" in text and "later turn" in text
    assert "`display`" in text and "instead of the function name" in text
    assert "`activity`" in text and "still set `display`" in text


def test_system_prompt_explains_argv_and_timeout():
    text = skill_argument_guidance()
    assert "`argv`" in text and '"--start"' in text
    assert "`timeout`" in text
    assert f"default {DEFAULT_TIMEOUT_SEC}" in text and f"at most {MAX_TIMEOUT_SEC}" in text


def test_system_prompt_explains_env_secrets():
    from open_webui.utils.secrets import secret_usage_hint

    with patch("open_webui.utils.secrets.list_secret_metadata", return_value=[]):
        hint = secret_usage_hint(SimpleNamespace(id="user-1"), webui_url="http://localhost:3000")
    assert "env_secrets" in hint
    assert "Only request the secrets" in hint
