"""Env-set keys pin PersistentConfig; unset keys still load/save from the DB."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from open_webui.config import (
    PERSISTENT_CONFIG_REGISTRY,
    AppConfig,
    PersistentConfig,
    persistent_config_env_is_set,
)


class PersistentConfigEnvIsSetTest(unittest.TestCase):
    def test_unset_is_not_set(self):
        os.environ.pop("WEATHER_SKILLS_TEST_UNSET", None)
        self.assertFalse(persistent_config_env_is_set("WEATHER_SKILLS_TEST_UNSET"))

    def test_empty_string_is_set(self):
        with patch.dict(os.environ, {"WEATHER_SKILLS_TEST_EMPTY": ""}):
            self.assertTrue(persistent_config_env_is_set("WEATHER_SKILLS_TEST_EMPTY"))

    def test_present_is_set(self):
        with patch.dict(os.environ, {"WEATHER_SKILLS_TEST_PRESENT": "false"}):
            self.assertTrue(persistent_config_env_is_set("WEATHER_SKILLS_TEST_PRESENT"))


class PersistentConfigPrecedenceTest(unittest.TestCase):
    def setUp(self):
        self._added: list[PersistentConfig] = []

    def tearDown(self):
        for item in self._added:
            try:
                PERSISTENT_CONFIG_REGISTRY.remove(item)
            except ValueError:
                pass

    def _make(
        self, env_name: str, env_value, db_value, **patch_env
    ) -> PersistentConfig:
        env = {k: str(v) for k, v in patch_env.items()}
        with patch.dict(os.environ, env, clear=False):
            if env_name not in env:
                os.environ.pop(env_name, None)
            with patch("open_webui.config.get_config_value", return_value=db_value):
                cfg = PersistentConfig(env_name, "test.flag", env_value)
        self._added.append(cfg)
        return cfg

    def test_env_wins_over_database(self):
        cfg = self._make(
            "WEATHER_SKILLS_TEST_PIN",
            True,
            False,
            WEATHER_SKILLS_TEST_PIN="true",
        )
        self.assertTrue(cfg.value)

    def test_database_used_when_env_unset(self):
        cfg = self._make("WEATHER_SKILLS_TEST_DB", True, False)
        self.assertFalse(cfg.value)

    def test_default_when_env_and_db_unset(self):
        cfg = self._make("WEATHER_SKILLS_TEST_DEFAULT", "default", None)
        self.assertEqual(cfg.value, "default")

    def test_update_does_not_clobber_env(self):
        cfg = self._make(
            "WEATHER_SKILLS_TEST_UPDATE",
            "from-env",
            "from-db",
            WEATHER_SKILLS_TEST_UPDATE="from-env",
        )
        with patch.dict(os.environ, {"WEATHER_SKILLS_TEST_UPDATE": "from-env"}):
            with patch(
                "open_webui.config.get_config_value", return_value="from-ui"
            ):
                cfg.update()
        self.assertEqual(cfg.value, "from-env")

    def test_update_applies_db_when_env_unset(self):
        cfg = self._make("WEATHER_SKILLS_TEST_UPDATE_DB", "from-env", "from-db")
        os.environ.pop("WEATHER_SKILLS_TEST_UPDATE_DB", None)
        with patch(
            "open_webui.config.get_config_value", return_value="from-ui"
        ):
            cfg.update()
        self.assertEqual(cfg.value, "from-ui")

    def test_appconfig_setattr_does_not_clobber_env(self):
        cfg = self._make(
            "WEATHER_SKILLS_TEST_UI",
            "from-env",
            "from-db",
            WEATHER_SKILLS_TEST_UI="from-env",
        )
        app = AppConfig()
        app.TEST_UI = cfg
        with patch.dict(os.environ, {"WEATHER_SKILLS_TEST_UI": "from-env"}):
            app.TEST_UI = "from-ui"
        self.assertEqual(app.TEST_UI, "from-env")
        self.assertEqual(cfg.value, "from-env")
