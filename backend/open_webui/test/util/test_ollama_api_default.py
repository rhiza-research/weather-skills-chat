"""ENABLE_OLLAMA_API is off unless the environment turns it on."""

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[3]

READ_FLAG = (
    "from open_webui.config import ENABLE_OLLAMA_API; print(ENABLE_OLLAMA_API.value)"
)


def ollama_api_enabled(env_value: str | None) -> bool:
    """Read ENABLE_OLLAMA_API from a fresh interpreter with an empty database.

    open_webui.config reads the variable once, at import, so each case needs its
    own process. The empty database means no value is saved from the admin
    settings, so only the environment and the default decide.
    """
    with tempfile.TemporaryDirectory() as data_dir:
        env = dict(os.environ)
        env["DATA_DIR"] = data_dir
        env["DATABASE_URL"] = f"sqlite:///{data_dir}/webui.db"
        env.pop("ENABLE_OLLAMA_API", None)
        if env_value is not None:
            env["ENABLE_OLLAMA_API"] = env_value
        result = subprocess.run(
            [sys.executable, "-c", READ_FLAG],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return result.stdout.strip().splitlines()[-1] == "True"


class OllamaApiDefaultTest(unittest.TestCase):
    def test_unset_is_off(self):
        self.assertFalse(ollama_api_enabled(None))

    def test_true_is_on(self):
        self.assertTrue(ollama_api_enabled("true"))

    def test_true_any_case_is_on(self):
        self.assertTrue(ollama_api_enabled("True"))

    def test_false_is_off(self):
        self.assertFalse(ollama_api_enabled("false"))


class NoOllamaAddressTest(unittest.TestCase):
    """OLLAMA_BASE_URLS defaults to no address, with the API on or off."""

    def _request(self, enabled: bool):
        app = SimpleNamespace(
            state=SimpleNamespace(
                config=SimpleNamespace(
                    ENABLE_OLLAMA_API=enabled,
                    OLLAMA_BASE_URLS=[],
                    OLLAMA_API_CONFIGS={},
                ),
                OLLAMA_MODELS=None,
            )
        )
        return SimpleNamespace(app=app)

    def test_model_list_is_empty(self):
        from open_webui.routers import ollama

        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                request = self._request(enabled)
                models = asyncio.run(ollama.get_all_models(request))
                self.assertEqual(models, {"models": []})
                self.assertEqual(request.app.state.OLLAMA_MODELS, {})

    def test_loaded_models_are_empty(self):
        from open_webui.routers import ollama

        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                result = asyncio.run(
                    ollama.get_ollama_loaded_models(self._request(enabled), user=None)
                )
                self.assertEqual(result, {})

    def test_version_reports_no_server(self):
        from fastapi import HTTPException

        from open_webui.routers import ollama

        self.assertEqual(
            asyncio.run(ollama.get_ollama_versions(self._request(False))),
            {"version": False},
        )
        with self.assertRaises(HTTPException) as raised:
            asyncio.run(ollama.get_ollama_versions(self._request(True)))
        self.assertEqual(raised.exception.status_code, 500)
