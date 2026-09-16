import json
import tempfile
import unittest
from pathlib import Path

from google.genai import types
from services.config_loader import BackendConfig
from services.realtime_constants import (
    GEMINI_3_8_LIVE_MODEL,
    GEMINI_3_8_LIVE_EXTENDED_THINKING_MODEL,
    _is_google_realtime_model,
    _is_google_thinking_realtime_model,
)
from services.realtime_voice_service import RealtimeVoiceService
from routers.settings import GOOGLE_MODEL_LIST_SUPPLEMENTS, AGENT_PLATFORM_MODEL_LIST_SUPPLEMENTS


class Gemini38LiveTests(unittest.TestCase):
    """Tests for Gemini 3.8 Live and Extended Thinking models."""

    def _config(self, initial: dict | None = None, **overrides) -> BackendConfig:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        config_path = Path(tmp_dir.name) / "config.json"
        config_path.write_text(json.dumps(initial or {}), encoding="utf-8")
        cfg = BackendConfig(config_path=config_path)
        cfg.reload(force=True)
        if overrides:
            cfg.update(overrides)
        return cfg

    def test_model_identifiers_and_classification(self):
        self.assertEqual(GEMINI_3_8_LIVE_MODEL, "gemini-3.8-live")
        self.assertEqual(GEMINI_3_8_LIVE_EXTENDED_THINKING_MODEL, "gemini-3.8-live-extended-thinking")

        self.assertTrue(_is_google_realtime_model(GEMINI_3_8_LIVE_MODEL))
        self.assertTrue(_is_google_realtime_model(GEMINI_3_8_LIVE_EXTENDED_THINKING_MODEL))

        self.assertFalse(_is_google_thinking_realtime_model(GEMINI_3_8_LIVE_MODEL))
        self.assertTrue(_is_google_thinking_realtime_model(GEMINI_3_8_LIVE_EXTENDED_THINKING_MODEL))

    def test_settings_supplements_include_gemini_3_8_live(self):
        self.assertIn("gemini-3.8-live", GOOGLE_MODEL_LIST_SUPPLEMENTS)
        self.assertIn("gemini-3.8-live-extended-thinking", GOOGLE_MODEL_LIST_SUPPLEMENTS)
        self.assertIn("gemini-3.8-live", AGENT_PLATFORM_MODEL_LIST_SUPPLEMENTS)
        self.assertIn("gemini-3.8-live-extended-thinking", AGENT_PLATFORM_MODEL_LIST_SUPPLEMENTS)

    def test_resolve_google_settings_preserves_models(self):
        cfg = self._config(api_keys={"google_api_key": "test-key"})
        service = RealtimeVoiceService(config=cfg)

        resolved_live = service._resolve_google_settings("gemini-3.8-live", provider="Google")
        self.assertEqual(resolved_live["model"], "gemini-3.8-live")

        resolved_thinking = service._resolve_google_settings("gemini-3.8-live-extended-thinking", provider="Google")
        self.assertEqual(resolved_thinking["model"], "gemini-3.8-live-extended-thinking")

    def test_build_live_config_standard_vs_thinking(self):
        cfg = self._config(api_keys={"google_api_key": "test-key"})
        service = RealtimeVoiceService(config=cfg)

        # Standard Gemini 3.8 Live
        config_standard = service._build_live_config(
            voice="Puck",
            instructions="You are a helpful assistant.",
            model="gemini-3.8-live",
        )
        self.assertIsNone(config_standard.thinking_config)
        for tool in config_standard.tools or []:
            for decl in getattr(tool, "function_declarations", None) or []:
                self.assertIsNone(decl.behavior)

        # Gemini 3.8 Live Extended Thinking
        config_thinking = service._build_live_config(
            voice="Puck",
            instructions="You are a helpful assistant.",
            model="gemini-3.8-live-extended-thinking",
        )
        self.assertIsNotNone(config_thinking.thinking_config)
        self.assertEqual(config_thinking.thinking_config.thinking_level, types.ThinkingLevel.LOW)

        tool_count = 0
        for tool in config_thinking.tools or []:
            for decl in getattr(tool, "function_declarations", None) or []:
                tool_count += 1
                self.assertEqual(decl.behavior, types.Behavior.NON_BLOCKING)
        self.assertGreater(tool_count, 0)


if __name__ == "__main__":
    unittest.main()
