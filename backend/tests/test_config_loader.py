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


class SaveAllAtomicityTests(unittest.TestCase):
    def _tmp_path(self) -> Path:
        return Path(tempfile.mkdtemp(prefix="vs_cfg_test_")) / "config.json"

    def test_save_all_is_atomic_and_leaves_no_tmp_file(self):
        config_path = self._tmp_path()
        config = BackendConfig(config_path)
        config.save_all({"api_keys": {"deepseek_api_key": "sk-1"}})
        self.assertEqual(
            json.loads(config_path.read_text(encoding="utf-8")),
            {"api_keys": {"deepseek_api_key": "sk-1"}},
        )
        self.assertFalse(config_path.with_name("config.json.tmp").exists())
        # .bak holds the previous good content after a second save.
        config.save_all({"api_keys": {"deepseek_api_key": "sk-2"}})
        backup = json.loads(
            config_path.with_name("config.json.bak").read_text(encoding="utf-8")
        )
        self.assertEqual(backup["api_keys"]["deepseek_api_key"], "sk-1")

    def test_save_all_refuses_to_overwrite_unreadable_file_with_empty_memory(self):
        config_path = self._tmp_path()
        original = {"api_keys": {"deepseek_api_key": "sk-precious"}}
        config_path.write_text(json.dumps(original), encoding="utf-8")
        config = BackendConfig(config_path)
        # Simulate the file becoming unreadable before anything was cached.
        config._config = {}
        config._mtime = None
        config._disk_unreadable = True
        with self.assertRaises(RuntimeError):
            config.update({"ui_settings": {"theme": "dark"}})
        # The original file must be untouched.
        self.assertEqual(
            json.loads(config_path.read_text(encoding="utf-8")), original
        )

    def test_reload_preserves_memory_snapshot_when_file_becomes_corrupt(self):
        config_path = self._tmp_path()
        config = BackendConfig(config_path)
        config.save_all({"api_keys": {"dashscope_api_key": "sk-live"}})
        config_path.write_text("{corrupted", encoding="utf-8")
        config.reload(force=True)
        self.assertEqual(config.peek_setting("dashscope_api_key"), "sk-live")

    def test_reload_recovers_from_backup_when_starting_on_corrupt_file(self):
        config_path = self._tmp_path()
        good = {"api_keys": {"groq_api_key": "gsk-bak"}}
        config_path.with_name("config.json.bak").write_text(
            json.dumps(good), encoding="utf-8"
        )
        config_path.write_text("{broken", encoding="utf-8")
        config = BackendConfig(config_path)
        self.assertEqual(config.peek_setting("groq_api_key"), "gsk-bak")

    def test_save_recovers_by_replacing_corrupt_file_when_memory_available(self):
        config_path = self._tmp_path()
        config_path.write_text(json.dumps({"api_keys": {"a": "b"}}), encoding="utf-8")
        config = BackendConfig(config_path)
        config_path.write_text("{corrupted", encoding="utf-8")
        config.reload(force=True)  # keeps in-memory snapshot
        config.update({"ui_settings": {"lang": "zh"}})
        saved = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["api_keys"], {"a": "b"})
        self.assertEqual(saved["ui_settings"], {"lang": "zh"})


if __name__ == "__main__":
    unittest.main()
