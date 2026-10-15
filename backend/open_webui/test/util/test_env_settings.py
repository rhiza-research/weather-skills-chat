"""Each setting reads its own variable or its alias, and bad input stops startup.

Settings are built when ``open_webui.config`` is imported, so each case
imports it in a fresh process with its own environment and database.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from open_webui import config
from open_webui.config import env_json

RESULT_MARK = "ENV_SETTINGS_RESULT:"

# Reads the named settings, then tries an admin save of each through AppConfig.
PROBE = f"""
import json, sys
from open_webui import config
from open_webui.config import AppConfig

app = AppConfig()
out = {{}}
for name in json.loads(sys.argv[1]):
    cfg = getattr(config, name)
    setattr(app, name, cfg)
    before = cfg.value
    setattr(app, name, ["saved-by-admin"])
    out[name] = {{"value": before, "after_save": getattr(app, name)}}
print({RESULT_MARK!r} + json.dumps(out))
"""

SAVE = """
import json, sys
from open_webui import config
from open_webui.config import AppConfig

app = AppConfig()
for name, value in json.loads(sys.argv[1]).items():
    setattr(app, name, getattr(config, name))
    setattr(app, name, value)
"""

JSON_SETTINGS = {
    "OLLAMA_API_CONFIGS": {"0": {"enable": True}},
    "OPENAI_API_CONFIGS": {"0": {"model_call_tracing": "openrouter"}},
    "TOOL_SERVER_CONNECTIONS": [
        {"url": "https://tools.example", "path": "openapi.json", "auth_type": "bearer"}
    ],
    "DEFAULT_PROMPT_SUGGESTIONS": [{"title": ["Hello", "world"], "content": "Hi"}],
    "MODEL_ORDER_LIST": ["weather-agent", "other"],
    "USER_PERMISSIONS": {"chat": {"edit": False}},
    "EVALUATION_ARENA_MODELS": [{"id": "arena", "name": "Arena", "meta": {}}],
    "WEB_SEARCH_DOMAIN_FILTER_LIST": ["example.org"],
    "COMFYUI_WORKFLOW_NODES": [{"type": "prompt", "key": "text", "node_ids": ["6"]}],
    "WEBUI_BANNERS": [
        {
            "id": "maintenance",
            "type": "info",
            "title": "Maintenance",
            "content": "Back soon",
            "dismissible": True,
            "timestamp": 1760400000,
        }
    ],
}

WRONG_TYPE = {
    "OLLAMA_API_CONFIGS": [],
    "OPENAI_API_CONFIGS": [],
    "TOOL_SERVER_CONNECTIONS": {},
    "DEFAULT_PROMPT_SUGGESTIONS": {},
    "MODEL_ORDER_LIST": {},
    "USER_PERMISSIONS": [],
    "EVALUATION_ARENA_MODELS": {},
    "WEB_SEARCH_DOMAIN_FILTER_LIST": "example.org",
    "COMFYUI_WORKFLOW_NODES": {},
    "WEBUI_BANNERS": {},
}

INVALID_ENTRY = {
    "OLLAMA_API_CONFIGS": {"first": {}},
    "OPENAI_API_CONFIGS": {"0": "openrouter"},
    "TOOL_SERVER_CONNECTIONS": [{"url": "https://tools.example"}],
    "DEFAULT_PROMPT_SUGGESTIONS": [{"title": "Hello", "content": "Hi"}],
    "MODEL_ORDER_LIST": ["weather-agent", 1],
    "USER_PERMISSIONS": {"chat": {"edit": "false"}},
    "EVALUATION_ARENA_MODELS": [{"id": "arena"}],
    "WEB_SEARCH_DOMAIN_FILTER_LIST": [1],
    "COMFYUI_WORKFLOW_NODES": ["prompt"],
    "WEBUI_BANNERS": [{"id": "x", "type": "info", "content": "Hi"}],
}

# Entries with a key the setting does not have.
UNKNOWN_KEY = {
    "TOOL_SERVER_CONNECTIONS": [
        {"url": "https://tools.example", "path": "openapi.json", "typo": 1}
    ],
    "DEFAULT_PROMPT_SUGGESTIONS": [{"title": ["Hi"], "content": "Hi", "typo": 1}],
    "EVALUATION_ARENA_MODELS": [{"id": "a", "name": "A", "meta": {}, "typo": 1}],
    "COMFYUI_WORKFLOW_NODES": [{"type": "prompt", "typo": 1}],
    "WEBUI_BANNERS": [{**JSON_SETTINGS["WEBUI_BANNERS"][0], "typo": 1}],
}

# Variables the app no longer reads at all, each set to a value that would
# change its old target if it were still read.
REMOVED_NAMES = {
    "OLLAMA_API_BASE_URL": "http://removed-ollama-api:11434/api",
    "K8S_FLAG": "true",
    "LDAP_SEARCH_FILTERS": "(objectClass=removed)",
    "OAUTH_GROUP_CLAIM": "removed-groups",
    "RAG_EMBEDDING_OPENAI_BATCH_SIZE": "7",
    "GEMINI_API_KEY": "removed-gemini-key",
    "GEMINI_API_BASE_URL": "https://removed-gemini.example",
}

# Admin settings a removed name used to feed, with their defaults.
FED_SETTING_DEFAULTS = {
    "OLLAMA_BASE_URLS": [],
    "RAG_OLLAMA_BASE_URL": "",
    "LDAP_SEARCH_FILTERS": "",
    "OAUTH_GROUPS_CLAIM": "groups",
    "RAG_EMBEDDING_BATCH_SIZE": 1,
    "IMAGES_GEMINI_API_KEY": "",
    "IMAGES_GEMINI_API_BASE_URL": "",
}

# Variables that still set their own setting but no longer feed another one.
FORMER_FEEDERS = {
    "CODE_EXECUTION_JUPYTER_URL": "http://other-jupyter:8888",
    "CODE_EXECUTION_JUPYTER_AUTH": "token",
    "CODE_EXECUTION_JUPYTER_AUTH_TOKEN": "other-token",
    "CODE_EXECUTION_JUPYTER_AUTH_PASSWORD": "other-password",
    "CODE_EXECUTION_JUPYTER_TIMEOUT": "7",
    "COMFYUI_WORKFLOW": "{}",
    "USE_OLLAMA_DOCKER": "true",
}

FORMERLY_FED_DEFAULTS = {
    "CODE_INTERPRETER_JUPYTER_URL": "",
    "CODE_INTERPRETER_JUPYTER_AUTH": "",
    "CODE_INTERPRETER_JUPYTER_AUTH_TOKEN": "",
    "CODE_INTERPRETER_JUPYTER_AUTH_PASSWORD": "",
    "CODE_INTERPRETER_JUPYTER_TIMEOUT": 60,
    "COMFYUI_WORKFLOW_NODES": [],
    "OLLAMA_BASE_URLS": [],
}

CONNECTION_LISTS = ("OPENAI_API_BASE_URLS", "OPENAI_API_KEYS", "OLLAMA_BASE_URLS")

# Each connection list's alias, a value for it, and the one-entry list it sets.
# The key holds a `;` to show an alias value is not split.
ALIASES = {
    "OPENAI_API_KEYS": ("OPENAI_API_KEY", "sk-one;two", ["sk-one;two"]),
    "OPENAI_API_BASE_URLS": (
        "OPENAI_API_BASE_URL",
        "https://openrouter.ai/api/v1",
        ["https://openrouter.ai/api/v1"],
    ),
    "OLLAMA_BASE_URLS": (
        "OLLAMA_BASE_URL",
        "http://ollama:11434/",
        ["http://ollama:11434"],
    ),
}

# Every variable these tests set or read; the child process starts without them.
CONTROLLED = (
    set(JSON_SETTINGS)
    | set(REMOVED_NAMES)
    | set(FED_SETTING_DEFAULTS)
    | set(FORMER_FEEDERS)
    | set(FORMERLY_FED_DEFAULTS)
    | set(CONNECTION_LISTS)
    | {alias for alias, _, _ in ALIASES.values()}
    | {"LDAP_SEARCH_FILTER"}
)


def _run(script: str, arg, env: dict, db_path: str) -> subprocess.CompletedProcess:
    child_env = {k: v for k, v in os.environ.items() if k not in CONTROLLED}
    child_env.update({"DATABASE_URL": f"sqlite:///{db_path}", **env})
    return subprocess.run(
        [sys.executable, "-c", script, json.dumps(arg)],
        env=child_env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _result(result: subprocess.CompletedProcess) -> dict:
    if result.returncode != 0:
        raise AssertionError(result.stderr[-4000:])
    for line in result.stdout.splitlines():
        if line.startswith(RESULT_MARK):
            return json.loads(line[len(RESULT_MARK) :])
    raise AssertionError(result.stdout[-4000:])


def _probe(names: list[str], env: dict, db_path: str) -> dict:
    return _result(_run(PROBE, names, env, db_path))


def _warning_lines(result: subprocess.CompletedProcess) -> str:
    """The both-names-set warnings the child logged, from either output stream."""
    lines = (result.stdout + result.stderr).splitlines()
    return "\n".join(line for line in lines if " are both set; " in line)


class EnvSettingsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "config.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_json_settings_read_their_variable_and_ignore_admin_saves(self):
        env = {name: json.dumps(value) for name, value in JSON_SETTINGS.items()}
        # OLLAMA_API_CONFIGS names connection 0, which needs an address.
        env["OLLAMA_BASE_URLS"] = "http://ollama:11434"
        result = _probe(list(JSON_SETTINGS), env, self.db_path)
        for name, value in JSON_SETTINGS.items():
            with self.subTest(name=name):
                self.assertEqual(result[name]["value"], value)
                self.assertEqual(result[name]["after_save"], value)

    def test_set_variable_wins_over_saved_value(self):
        saved = {"0": {"model_call_tracing": "app"}}
        result = _run(SAVE, {"OPENAI_API_CONFIGS": saved}, {}, self.db_path)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        pinned = {"0": {"model_call_tracing": "openrouter"}}
        probe = _probe(
            ["OPENAI_API_CONFIGS"],
            {"OPENAI_API_CONFIGS": json.dumps(pinned)},
            self.db_path,
        )
        self.assertEqual(probe["OPENAI_API_CONFIGS"]["value"], pinned)
        self.assertEqual(probe["OPENAI_API_CONFIGS"]["after_save"], pinned)

    def test_unset_variable_uses_saved_value_and_admin_saves_work(self):
        saved = {"0": {"model_call_tracing": "openrouter"}}
        result = _run(SAVE, {"OPENAI_API_CONFIGS": saved}, {}, self.db_path)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        probe = _probe(["OPENAI_API_CONFIGS"], {}, self.db_path)
        self.assertEqual(probe["OPENAI_API_CONFIGS"]["value"], saved)
        self.assertEqual(
            probe["OPENAI_API_CONFIGS"]["after_save"], ["saved-by-admin"]
        )

    def test_bad_json_stops_startup_and_names_the_variable(self):
        for name in ("TOOL_SERVER_CONNECTIONS", "WEBUI_BANNERS"):
            with self.subTest(name=name):
                result = _run(PROBE, [name], {name: "[{"}, self.db_path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{name} is not valid JSON", result.stderr)

    def test_wrong_type_stops_startup_and_names_variable_and_type(self):
        for name, value in WRONG_TYPE.items():
            with self.subTest(name=name):
                result = _run(PROBE, [name], {name: json.dumps(value)}, self.db_path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{name} must be a JSON", result.stderr)

    def test_invalid_entry_stops_startup_and_names_the_variable(self):
        for name, value in INVALID_ENTRY.items():
            with self.subTest(name=name):
                result = _run(PROBE, [name], {name: json.dumps(value)}, self.db_path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{name} must be a JSON", result.stderr)

    def test_unknown_key_stops_startup_and_names_the_variable(self):
        for name, value in UNKNOWN_KEY.items():
            with self.subTest(name=name):
                result = _run(PROBE, [name], {name: json.dumps(value)}, self.db_path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{name} must be a JSON", result.stderr)

    def test_connection_settings_for_a_missing_address_stop_startup(self):
        for name, value in (
            ("OPENAI_API_CONFIGS", {"1": {}}),
            ("OLLAMA_API_CONFIGS", {"0": {}}),
        ):
            with self.subTest(name=name):
                result = _run(PROBE, [name], {name: json.dumps(value)}, self.db_path)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{name} has settings for connection", result.stderr)

    def test_settings_read_their_own_names(self):
        env = {
            "OAUTH_GROUPS_CLAIM": "teams",
            "LDAP_SEARCH_FILTER": "(objectClass=person)",
            "COMFYUI_WORKFLOW_NODES": json.dumps([{"type": "prompt"}]),
        }
        result = _probe(
            ["OAUTH_GROUPS_CLAIM", "LDAP_SEARCH_FILTERS", "COMFYUI_WORKFLOW_NODES"],
            env,
            self.db_path,
        )
        self.assertEqual(result["OAUTH_GROUPS_CLAIM"]["after_save"], "teams")
        self.assertEqual(
            result["LDAP_SEARCH_FILTERS"]["after_save"], "(objectClass=person)"
        )
        self.assertEqual(
            result["COMFYUI_WORKFLOW_NODES"]["after_save"], [{"type": "prompt"}]
        )

    def test_removed_names_feed_no_setting(self):
        result = _probe(list(FED_SETTING_DEFAULTS), REMOVED_NAMES, self.db_path)
        for name, default in FED_SETTING_DEFAULTS.items():
            with self.subTest(name=name):
                self.assertEqual(result[name]["value"], default)
                self.assertEqual(result[name]["after_save"], ["saved-by-admin"])

    def test_former_feeders_set_only_their_own_setting(self):
        result = _probe(list(FORMERLY_FED_DEFAULTS), FORMER_FEEDERS, self.db_path)
        for name, default in FORMERLY_FED_DEFAULTS.items():
            with self.subTest(name=name):
                self.assertEqual(result[name]["value"], default)
                self.assertEqual(result[name]["after_save"], ["saved-by-admin"])

    def test_connection_lists_are_split_and_ollama_trailing_slash_removed(self):
        env = {
            "OPENAI_API_BASE_URLS": "https://openrouter.ai/api/v1; https://api.example/v1",
            "OPENAI_API_KEYS": "sk-a;sk-b",
            "OLLAMA_BASE_URLS": "http://ollama:11434/;http://other:11434",
        }
        result = _probe(list(env), env, self.db_path)
        self.assertEqual(
            result["OPENAI_API_BASE_URLS"]["value"],
            ["https://openrouter.ai/api/v1", "https://api.example/v1"],
        )
        self.assertEqual(result["OPENAI_API_KEYS"]["value"], ["sk-a", "sk-b"])
        self.assertEqual(
            result["OLLAMA_BASE_URLS"]["value"],
            ["http://ollama:11434", "http://other:11434"],
        )

    def test_empty_connection_list_entry_stops_startup(self):
        for name in CONNECTION_LISTS:
            for value in ("", "http://a.example;", ";http://a.example"):
                with self.subTest(name=name, value=value):
                    result = _run(PROBE, [name], {name: value}, self.db_path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"{name} has an empty entry", result.stderr)

    def test_different_counts_of_addresses_and_keys_stop_startup(self):
        env = {
            "OPENAI_API_BASE_URLS": "https://a.example/v1;https://b.example/v1",
            "OPENAI_API_KEYS": "sk-a",
        }
        result = _run(PROBE, ["OPENAI_API_KEYS"], env, self.db_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OPENAI_API_BASE_URLS has 2 entries", result.stderr)
        self.assertIn("OPENAI_API_KEYS has 1", result.stderr)

    def test_alias_sets_a_one_entry_list_that_wins_over_saved_value(self):
        saved = {name: ["saved-before-start"] for name in ALIASES}
        result = _run(SAVE, saved, {}, self.db_path)
        self.assertEqual(result.returncode, 0, result.stderr[-4000:])
        env = {alias: value for alias, value, _ in ALIASES.values()}
        probe = _probe(list(ALIASES) + ["RAG_OLLAMA_BASE_URL"], env, self.db_path)
        for name, (alias, _, expected) in ALIASES.items():
            with self.subTest(name=name, alias=alias):
                self.assertEqual(probe[name]["value"], expected)
                self.assertEqual(probe[name]["after_save"], expected)
        # OLLAMA_BASE_URL sets only the Ollama connections.
        self.assertEqual(probe["RAG_OLLAMA_BASE_URL"]["value"], "")

    def test_empty_alias_stops_startup(self):
        for name, (alias, _, _) in ALIASES.items():
            for value in ("", "  "):
                with self.subTest(alias=alias, value=value):
                    result = _run(PROBE, [name], {alias: value}, self.db_path)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"{alias} is empty", result.stderr)

    def test_alias_alone_logs_no_warning(self):
        for name, (alias, value, _) in ALIASES.items():
            with self.subTest(name=name, alias=alias):
                result = _run(PROBE, [name], {alias: value}, self.db_path)
                _result(result)
                self.assertEqual(_warning_lines(result), "")

    def test_plural_wins_when_both_names_are_set_and_a_warning_names_both(self):
        plural_values = {
            "OPENAI_API_KEYS": ("sk-plural", ["sk-plural"]),
            "OPENAI_API_BASE_URLS": (
                "https://plural.example/v1",
                ["https://plural.example/v1"],
            ),
            "OLLAMA_BASE_URLS": ("http://plural:11434", ["http://plural:11434"]),
        }
        for name, (alias, alias_value, _) in ALIASES.items():
            plural_value, expected = plural_values[name]
            with self.subTest(name=name, alias=alias):
                result = _run(
                    PROBE, [name], {name: plural_value, alias: alias_value}, self.db_path
                )
                probe = _result(result)
                self.assertEqual(probe[name]["value"], expected)
                self.assertEqual(probe[name]["after_save"], expected)
                warnings = _warning_lines(result)
                self.assertEqual(
                    warnings.count(f"{name} and {alias} are both set; using {name}"), 1
                )
                self.assertNotIn(plural_value, warnings)
                self.assertNotIn(alias_value.strip("/"), warnings)

    def test_alias_counts_as_one_entry_against_the_other_list(self):
        env = {
            "OPENAI_API_BASE_URLS": "https://a.example/v1;https://b.example/v1",
            "OPENAI_API_KEY": "sk-a",
        }
        result = _run(PROBE, ["OPENAI_API_KEYS"], env, self.db_path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OPENAI_API_BASE_URLS has 2 entries", result.stderr)
        self.assertIn("OPENAI_API_KEY has 1", result.stderr)


class SettingWiringTest(unittest.TestCase):
    def test_settings_are_pinned_by_their_own_variable(self):
        for name in list(JSON_SETTINGS) + ["OAUTH_GROUPS_CLAIM"]:
            with self.subTest(name=name):
                self.assertEqual(getattr(config, name).env_name, name)
        self.assertEqual(config.LDAP_SEARCH_FILTERS.env_name, "LDAP_SEARCH_FILTER")


class EnvJsonTest(unittest.TestCase):
    def test_absent_variable_returns_default(self):
        os.environ.pop("WEATHER_SKILLS_TEST_JSON", None)
        default = {"kept": True}
        self.assertIs(
            env_json("WEATHER_SKILLS_TEST_JSON", default, dict, "a JSON object"),
            default,
        )

    def test_empty_value_is_bad_json(self):
        with patch.dict(os.environ, {"WEATHER_SKILLS_TEST_JSON": ""}):
            with self.assertRaisesRegex(ValueError, "WEATHER_SKILLS_TEST_JSON"):
                env_json("WEATHER_SKILLS_TEST_JSON", {}, dict, "a JSON object")

    def test_value_is_returned_as_given(self):
        value = {"0": {"extra": [1, 2]}}
        with patch.dict(os.environ, {"WEATHER_SKILLS_TEST_JSON": json.dumps(value)}):
            self.assertEqual(
                env_json(
                    "WEATHER_SKILLS_TEST_JSON",
                    {},
                    config.CONNECTION_CONFIGS_SCHEMA,
                    config.CONNECTION_CONFIGS_EXPECTED,
                ),
                value,
            )


if __name__ == "__main__":
    unittest.main()
