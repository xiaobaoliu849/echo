import json
import tempfile
import unittest
from pathlib import Path

from services.config_loader import BackendConfig
from services.llm_service import LLMService
from services.realtime_constants import (
    DEFAULT_GOOGLE_REALTIME_VOICE,
    DEFAULT_VERCEL_REALTIME_MODEL,
    DEFAULT_VERCEL_REALTIME_VOICE,
    VERCEL_GEMINI_3_8_LIVE,
    VERCEL_GEMINI_3_8_LIVE_EXTENDED_THINKING,
    _is_vercel_realtime_model,
)
from services.realtime_vercel_provider import (
    VercelRealtimeMixin,
    _normalize_vercel_voice,
)
from services.realtime_voice_service import RealtimeVoiceService
from routers.settings import VERCEL_MODEL_LIST_SUPPLEMENTS


class VercelGemini38LiveTests(unittest.TestCase):
    """Tests for Gemini 3.8 Live & Extended Thinking on Vercel AI Gateway."""

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

    def test_model_constants_and_detection(self):
        self.assertEqual(VERCEL_GEMINI_3_8_LIVE, "google/gemini-3.8-live")
        self.assertEqual(VERCEL_GEMINI_3_8_LIVE_EXTENDED_THINKING, "google/gemini-3.8-live-extended-thinking")

        # Models with 'live' under creator/model-name format are identified as Vercel realtime models
        self.assertTrue(_is_vercel_realtime_model("google/gemini-3.8-live"))
        self.assertTrue(_is_vercel_realtime_model("google/gemini-3.8-live-extended-thinking"))
        self.assertTrue(_is_vercel_realtime_model("openai/gpt-realtime-2"))
        self.assertTrue(_is_vercel_realtime_model("spacexai/grok-voice-think-fast-1.0"))

        # Non-realtime or non-gateway models
        self.assertFalse(_is_vercel_realtime_model("google/gemini-2.5-flash"))
        self.assertFalse(_is_vercel_realtime_model("openai/gpt-4o"))
        self.assertFalse(_is_vercel_realtime_model("gemini-3.8-live"))  # missing provider prefix
        self.assertFalse(_is_vercel_realtime_model(""))

    def test_settings_supplements_include_gemini_3_8_live(self):
        self.assertIn("google/gemini-3.8-live", VERCEL_MODEL_LIST_SUPPLEMENTS)
        self.assertIn("google/gemini-3.8-live-extended-thinking", VERCEL_MODEL_LIST_SUPPLEMENTS)

    def test_normalize_vercel_voice(self):
        # Google Gemini models require Google voices (default Puck)
        self.assertEqual(_normalize_vercel_voice("google/gemini-3.8-live", ""), DEFAULT_GOOGLE_REALTIME_VOICE)
        self.assertEqual(_normalize_vercel_voice("google/gemini-3.8-live", "alloy"), DEFAULT_GOOGLE_REALTIME_VOICE)
        self.assertEqual(_normalize_vercel_voice("google/gemini-3.8-live", "Zephyr"), "Zephyr")
        self.assertEqual(_normalize_vercel_voice("google/gemini-3.8-live-extended-thinking", "Aoede"), "Aoede")
        self.assertEqual(_normalize_vercel_voice("google/gemini-3.8-live-extended-thinking", "invalid-voice"), DEFAULT_GOOGLE_REALTIME_VOICE)

        # OpenAI models require OpenAI voices (default alloy)
        self.assertEqual(_normalize_vercel_voice("openai/gpt-realtime-2", ""), DEFAULT_VERCEL_REALTIME_VOICE)
        self.assertEqual(_normalize_vercel_voice("openai/gpt-realtime-2", "Puck"), DEFAULT_VERCEL_REALTIME_VOICE)
        self.assertEqual(_normalize_vercel_voice("openai/gpt-realtime-2", "echo"), "echo")
        self.assertEqual(_normalize_vercel_voice("openai/gpt-realtime-2", "invalid-voice"), DEFAULT_VERCEL_REALTIME_VOICE)

    def test_vercel_ws_url_resolution(self):
        service = RealtimeVoiceService(config=self._config(api_keys={"vercel_api_key": "test-key"}))

        # Bare origin
        settings = {"base_url": "https://ai-gateway.vercel.sh", "model": "google/gemini-3.8-live"}
        ws_url = service._vercel_ws_url(settings)
        self.assertEqual(
            ws_url,
            "wss://ai-gateway.vercel.sh/v4/ai/realtime-model?ai-model-id=google%2Fgemini-3.8-live",
        )

        # Origin with /v1
        settings_v1 = {"base_url": "https://ai-gateway.vercel.sh/v1", "model": "google/gemini-3.8-live-extended-thinking"}
        ws_url_v1 = service._vercel_ws_url(settings_v1)
        self.assertEqual(
            ws_url_v1,
            "wss://ai-gateway.vercel.sh/v4/ai/realtime-model?ai-model-id=google%2Fgemini-3.8-live-extended-thinking",
        )

    def test_llm_service_vercel_chat_url(self):
        # Bare base URL gets /v1/chat/completions
        url = LLMService._build_chat_completions_url("Vercel", "https://ai-gateway.vercel.sh")
        self.assertEqual(url, "https://ai-gateway.vercel.sh/v1/chat/completions")

        # Base URL already ending with /v1 gets /chat/completions without duplicate /v1
        url_with_v1 = LLMService._build_chat_completions_url("Vercel", "https://ai-gateway.vercel.sh/v1")
        self.assertEqual(url_with_v1, "https://ai-gateway.vercel.sh/v1/chat/completions")

        # Other providers are unchanged
        url_deepseek = LLMService._build_chat_completions_url("DeepSeek", "https://api.deepseek.com/v1")
        self.assertEqual(url_deepseek, "https://api.deepseek.com/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
