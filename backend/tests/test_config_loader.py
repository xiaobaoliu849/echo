"""Tests for BackendConfig config loading helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from services.config_loader import BackendConfig


class PeekSettingTests(unittest.TestCase):
    def _make_config(self, payload: dict) -> BackendConfig:
        config_path = Path(tempfile.mkdtemp(prefix="vs_cfg_test_")) / "config.json"
        config_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return BackendConfig(config_path)

    def test_matches_get_setting_for_top_level_and_api_keys(self):
        config = self._make_config({
            "api_keys": {"dashscope_api_key": "sk-test"},
            "doubao_app_id": "123456",
        })
        for key in ("dashscope_api_key", "doubao_app_id", "missing_key"):
            self.assertEqual(
                config.peek_setting(key, "default"),
                config.get_setting(key, "default"),
            )
        self.assertEqual(config.peek_setting("dashscope_api_key"), "sk-test")
        self.assertEqual(config.peek_setting("doubao_app_id"), "123456")
        self.assertEqual(config.peek_setting("missing_key", ""), "")

    def test_peek_returns_live_reference_caller_must_not_mutate(self):
        config = self._make_config({"api_keys": {"k": "v"}})
        # peek shares the in-memory dict; get_all must still deep-copy.
        self.assertIs(config.peek_setting("api_keys"), config._config["api_keys"])
        self.assertIsNot(config.get_all()["api_keys"], config._config["api_keys"])


if __name__ == "__main__":
    unittest.main()
