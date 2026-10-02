"""ENABLE_OLLAMA_API is off unless the environment turns it on."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
