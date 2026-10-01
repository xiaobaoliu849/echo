import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch
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

    def test_avatar_config_uses_real_model_video_and_selected_face(self):
        config = RealtimeVoiceService._build_live_config(model="gemini-3.8-live", voice="Puck", avatar_name="Ben")
        self.assertEqual(config.response_modalities, [types.Modality.VIDEO])
        self.assertEqual(config.avatar_config.avatar_name, "Ben")
        self.assertEqual(config.speech_config.voice_config.prebuilt_voice_config.voice_name, "Puck")
        audio = RealtimeVoiceService._build_live_config(model="gemini-3.8-live")
        self.assertEqual(audio.response_modalities, [types.Modality.AUDIO])
        self.assertIsNone(audio.avatar_config)

    def test_mp4_never_enters_pcm_audio_stream(self):
        message = types.LiveServerMessage(server_content=types.LiveServerContent(model_turn=types.Content(parts=[
            types.Part(inline_data=types.Blob(mime_type="video/mp4", data=b"mp4")),
            types.Part(inline_data=types.Blob(mime_type="audio/pcm;rate=24000", data=b"pcm")),
        ])))
        self.assertEqual(RealtimeVoiceService._extract_google_pcm(message), b"pcm")
        message.server_content.model_turn.parts.pop()
        self.assertIsNone(RealtimeVoiceService._extract_google_pcm(message))

    def test_avatar_uses_regional_oauth_even_with_api_key_configured(self):
        with patch("services.realtime_google_provider.resolve_agent_platform_service_account_file", return_value=""), \
             patch("google.auth.default", return_value=(MagicMock(), "adc-project")), \
             patch("services.realtime_google_provider.genai.Client") as client:
            RealtimeVoiceService._create_agent_platform_client(
                {"api_key": "studio-key", "project_id": "my-project", "location": "eu"}, avatar=True, live_translate=False,
            )
            self.assertEqual(client.call_args.kwargs["project"], "my-project")
            self.assertEqual(client.call_args.kwargs["location"], "eu")
            self.assertEqual(client.call_args.kwargs["http_options"], {"api_version": "v1"})
            self.assertIn("credentials", client.call_args.kwargs)
            self.assertNotIn("api_key", client.call_args.kwargs)

    def test_avatar_rejects_unsupported_region(self):
        with self.assertRaisesRegex(ValueError, "region"):
            RealtimeVoiceService._create_agent_platform_client({"location": "global"}, avatar=True, live_translate=False)

    def test_explicit_missing_credential_file_is_not_replaced_by_another_account(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            RealtimeVoiceService._create_agent_platform_client(
                {"sa_file": "C:/nonexistent-echo-test/account.json"}, avatar=True, live_translate=False,
            )

    def test_cloud_settings_preserve_explicit_service_account_path(self):
        cfg = self._config(api_keys={"vertex_sa_file": "C:/credentials/test.json", "vertex_project_id": "my-project"})
        settings = RealtimeVoiceService(cfg)._resolve_google_settings("gemini-3.8-live", provider="AgentPlatform")
        self.assertEqual(settings["sa_file"], "C:/credentials/test.json")
        self.assertEqual(settings["project_id"], "my-project")

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
        self.assertEqual(
            config_standard.realtime_input_config.activity_handling,
            types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        )
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
        self.assertEqual(
            config_thinking.realtime_input_config.activity_handling,
            types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        )

        tool_count = 0
        for tool in config_thinking.tools or []:
            for decl in getattr(tool, "function_declarations", None) or []:
                tool_count += 1
                self.assertEqual(decl.behavior, types.Behavior.NON_BLOCKING)
        self.assertGreater(tool_count, 0)


if __name__ == "__main__":
    unittest.main()
