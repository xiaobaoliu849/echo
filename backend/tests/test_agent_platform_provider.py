import unittest
from unittest.mock import AsyncMock, patch

from services.config_loader import BackendConfig
from services.llm_service import LLMService
from services.realtime_voice_service import RealtimeVoiceService


class AgentPlatformProviderTests(unittest.IsolatedAsyncioTestCase):
    """Google Agent Platform (formerly Vertex AI) provider key tests.

    Canonical provider key is "AgentPlatform"; legacy "VertexAI" must keep
    working at every boundary (config sections, service lookups, LLM routing,
    realtime session resolution).
    """

    def test_agent_platform_provider_settings_resolution(self):
        cfg = BackendConfig()
        cfg.update({
            "api_keys": {
                "vertex_api_key": "AQ-mock-vertex-key",
                "vertex_project_id": "my-gcp-project",
                "vertex_location": "us-central1",
            },
            "api_urls": {
                "AgentPlatform": "https://us-central1-aiplatform.googleapis.com/v1",
            },
        })
        settings = cfg.get_provider_settings("AgentPlatform")
        self.assertEqual(settings["provider"], "AgentPlatform")
        self.assertEqual(settings["api_key"], "AQ-mock-vertex-key")
        self.assertEqual(settings["project_id"], "my-gcp-project")
        self.assertEqual(settings["location"], "us-central1")
        self.assertIn("aiplatform.googleapis.com", settings["base_url"])

    def test_legacy_vertexai_config_section_migrates_on_load(self):
        """Legacy config.json with "VertexAI" section keys must be migrated to
        "AgentPlatform" on load and keep serving both old and new lookups."""
        import json
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(json.dumps({
                "api_keys": {
                    "vertex_api_key": "AQ-mock-vertex-key",
                    "vertex_project_id": "my-gcp-project",
                },
                "api_urls": {
                    "VertexAI": "https://us-central1-aiplatform.googleapis.com/v1",
                },
                "default_models": {
                    "VertexAI": "gemini-3.5-live-translate-preview",
                },
            }), encoding="utf-8")

            cfg = BackendConfig(config_path=config_path)
            cfg.reload(force=True)
            # Sections must have been renamed in the loaded config.
            self.assertNotIn("VertexAI", cfg.get_all().get("api_urls", {}))
            self.assertIn("AgentPlatform", cfg.get_all().get("api_urls", {}))
            self.assertNotIn("VertexAI", cfg.get_all().get("default_models", {}))
            self.assertIn("AgentPlatform", cfg.get_all().get("default_models", {}))
            # Legacy lookup still resolves, and reports the canonical provider.
            legacy = cfg.get_provider_settings("VertexAI")
            self.assertEqual(legacy["provider"], "AgentPlatform")
            self.assertIn("aiplatform.googleapis.com", legacy["base_url"])
            self.assertEqual(legacy["model"], "gemini-3.5-live-translate-preview")
            # Canonical lookup resolves identically.
            canonical = cfg.get_provider_settings("AgentPlatform")
            self.assertEqual(canonical["base_url"], legacy["base_url"])
            self.assertEqual(canonical["model"], legacy["model"])

    def test_agent_platform_default_model(self):
        cfg = BackendConfig()
        settings = cfg.get_provider_settings("AgentPlatform")
        self.assertTrue(settings["model"].startswith("gemini-"))

    async def test_llm_service_routes_agent_platform(self):
        cfg = BackendConfig()
        cfg.update({
            "api_keys": {
                "vertex_api_key": "AQ-mock-vertex-key",
            },
        })
        llm = LLMService(cfg)
        mock_response = {
            "provider": "AgentPlatform",
            "model": "gemini-2.5-flash",
            "reply": "Hello from Agent Platform!",
            "raw": {},
        }
        for provider in ("AgentPlatform", "VertexAI"):
            with self.subTest(provider=provider):
                with patch.object(llm, "_chat_completion_google", new_callable=AsyncMock) as mock_google:
                    mock_google.return_value = mock_response
                    result = await llm.chat_completion(
                        provider=provider,
                        messages=[{"role": "user", "content": "hi"}],
                        model="gemini-2.5-flash",
                        use_memory=False,
                    )
                    self.assertEqual(result["reply"], "Hello from Agent Platform!")
                    mock_google.assert_awaited_once()

    def test_realtime_voice_service_resolves_agent_platform_settings(self):
        cfg = BackendConfig()
        cfg.update({
            "api_keys": {
                "vertex_api_key": "AQ-mock-vertex-key",
            },
        })
        service = RealtimeVoiceService(cfg)
        for provider in ("AgentPlatform", "VertexAI"):
            with self.subTest(provider=provider):
                resolved = service._resolve_google_settings(
                    "gemini-3.5-live-translate-preview", provider=provider
                )
                self.assertEqual(resolved["provider"], "AgentPlatform")
                self.assertEqual(resolved["api_key"], "AQ-mock-vertex-key")
                self.assertEqual(resolved["model"], "gemini-3.5-live-translate-preview")

    def test_agent_platform_catalog_includes_native_audio(self):
        """The native-audio realtime model must be in the AgentPlatform catalog
        so the frontend can route it through Google Cloud quota instead of AI
        Studio quota, while studio-only preview models must not be included."""
        from services.settings_service import DEFAULT_SETTINGS_TEMPLATE
        vertex_models = DEFAULT_SETTINGS_TEMPLATE["default_models"]["AgentPlatform"]
        self.assertIn(
            "gemini-live-2.5-flash-native-audio",
            vertex_models["available"],
        )
        self.assertIn(
            "gemini-live-2.5-flash-native-audio",
            vertex_models["enabled"],
        )
        self.assertNotIn(
            "gemini-3.1-flash-live-preview",
            vertex_models["available"],
        )
        self.assertNotIn(
            "gemini-2.5-flash-native-audio-preview-12-2025",
            vertex_models["available"],
        )

    def test_realtime_voice_service_resolves_agent_platform_native_audio(self):
        """Resolving settings for the native-audio model under AgentPlatform
        must return the AgentPlatform provider, key, and the requested model."""
        cfg = BackendConfig()
        cfg.update({
            "api_keys": {
                "vertex_api_key": "AQ-mock-vertex-key",
            },
        })
        service = RealtimeVoiceService(cfg)
        resolved = service._resolve_google_settings(
            "gemini-live-2.5-flash-native-audio", provider="AgentPlatform"
        )
        self.assertEqual(resolved["provider"], "AgentPlatform")
        self.assertEqual(resolved["api_key"], "AQ-mock-vertex-key")
        self.assertEqual(resolved["model"], "gemini-live-2.5-flash-native-audio")


if __name__ == "__main__":
    unittest.main()
