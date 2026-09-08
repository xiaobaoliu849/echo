import unittest
from unittest.mock import AsyncMock, patch

from services.config_loader import BackendConfig
from services.llm_service import LLMService
from services.realtime_voice_service import RealtimeVoiceService


class VertexAIProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_vertex_ai_provider_settings_resolution(self):
        cfg = BackendConfig()
        cfg.update({
            "api_keys": {
                "vertex_api_key": "AQ-mock-vertex-key",
                "vertex_project_id": "my-gcp-project",
                "vertex_location": "us-central1",
            },
            "api_urls": {
                "VertexAI": "https://us-central1-aiplatform.googleapis.com/v1",
            },
        })
        settings = cfg.get_provider_settings("VertexAI")
        self.assertEqual(settings["api_key"], "AQ-mock-vertex-key")
        self.assertEqual(settings["project_id"], "my-gcp-project")
        self.assertEqual(settings["location"], "us-central1")
        self.assertIn("aiplatform.googleapis.com", settings["base_url"])

    def test_vertex_ai_default_model(self):
        cfg = BackendConfig()
        settings = cfg.get_provider_settings("VertexAI")
        self.assertTrue(settings["model"].startswith("gemini-"))

    async def test_llm_service_routes_vertex_ai(self):
        cfg = BackendConfig()
        cfg.update({
            "api_keys": {
                "vertex_api_key": "AQ-mock-vertex-key",
            },
        })
        llm = LLMService(cfg)
        mock_response = {
            "provider": "VertexAI",
            "model": "gemini-2.5-flash",
            "reply": "Hello from Vertex!",
            "raw": {},
        }
        with patch.object(llm, "_chat_completion_google", new_callable=AsyncMock) as mock_google:
            mock_google.return_value = mock_response
            result = await llm.chat_completion(
                provider="VertexAI",
                messages=[{"role": "user", "content": "hi"}],
                model="gemini-2.5-flash",
                use_memory=False,
            )
            self.assertEqual(result["reply"], "Hello from Vertex!")
            mock_google.assert_awaited_once()

    def test_realtime_voice_service_resolves_vertex_settings(self):
        cfg = BackendConfig()
        cfg.update({
            "api_keys": {
                "vertex_api_key": "AQ-mock-vertex-key",
            },
        })
        service = RealtimeVoiceService(cfg)
        resolved = service._resolve_google_settings("gemini-3.5-live-translate-preview", provider="VertexAI")
        self.assertEqual(resolved["provider"], "VertexAI")
        self.assertEqual(resolved["api_key"], "AQ-mock-vertex-key")
        self.assertEqual(resolved["model"], "gemini-3.5-live-translate-preview")


if __name__ == "__main__":
    unittest.main()
