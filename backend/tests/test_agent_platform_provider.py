import json
import tempfile
import unittest
from pathlib import Path
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

    def _config(self, initial: dict | None = None, **overrides) -> BackendConfig:
        """Build a BackendConfig backed by a throwaway file.

        Never use a bare ``BackendConfig()`` here: it resolves to the real user
        config (``%APPDATA%/Echo/config.json``), and ``cfg.update()`` persists
        to disk — so the mock keys below would overwrite the user's live API
        keys the moment the suite runs.
        """
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        config_path = Path(tmp_dir.name) / "config.json"
        config_path.write_text(json.dumps(initial or {}), encoding="utf-8")
        cfg = BackendConfig(config_path=config_path)
        cfg.reload(force=True)
        if overrides:
            cfg.update(overrides)
        return cfg

    def test_isolated_config_never_targets_the_real_user_config(self):
        """Guard for the helper itself: a regression here silently leaks mock
        keys into the user's live config, which is unrecoverable damage."""
        cfg = self._config(api_keys={"vertex_api_key": "AQ-mock-vertex-key"})
        real_path = Path(BackendConfig._default_config_path()).resolve()
        self.assertNotEqual(Path(cfg.config_path).resolve(), real_path)
        self.assertEqual(Path(cfg.config_path).name, "config.json")
        # And the write really did land in the temp file.
        on_disk = json.loads(Path(cfg.config_path).read_text(encoding="utf-8"))
        self.assertEqual(on_disk["api_keys"]["vertex_api_key"], "AQ-mock-vertex-key")

    def test_agent_platform_provider_settings_resolution(self):
        cfg = self._config(
            api_keys={
                "vertex_api_key": "AQ-mock-vertex-key",
                "vertex_project_id": "my-gcp-project",
                "vertex_location": "us-central1",
            },
            api_urls={
                "AgentPlatform": "https://us-central1-aiplatform.googleapis.com/v1",
            },
        )
        settings = cfg.get_provider_settings("AgentPlatform")
        self.assertEqual(settings["provider"], "AgentPlatform")
        self.assertEqual(settings["api_key"], "AQ-mock-vertex-key")
        self.assertEqual(settings["project_id"], "my-gcp-project")
        self.assertEqual(settings["location"], "us-central1")
        self.assertIn("aiplatform.googleapis.com", settings["base_url"])

    def test_legacy_vertexai_config_section_migrates_on_load(self):
        """Legacy config.json with "VertexAI" section keys must be migrated to
        "AgentPlatform" on load and keep serving both old and new lookups."""
        cfg = self._config({
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
        })
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
        cfg = self._config()
        settings = cfg.get_provider_settings("AgentPlatform")
        self.assertTrue(settings["model"].startswith("gemini-"))

    async def test_llm_service_routes_agent_platform(self):
        cfg = self._config(api_keys={"vertex_api_key": "AQ-mock-vertex-key"})
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
        cfg = self._config(api_keys={"vertex_api_key": "AQ-mock-vertex-key"})
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
        cfg = self._config(api_keys={"vertex_api_key": "AQ-mock-vertex-key"})
        service = RealtimeVoiceService(cfg)
        resolved = service._resolve_google_settings(
            "gemini-live-2.5-flash-native-audio", provider="AgentPlatform"
        )
        self.assertEqual(resolved["provider"], "AgentPlatform")
        self.assertEqual(resolved["api_key"], "AQ-mock-vertex-key")
        self.assertEqual(resolved["model"], "gemini-live-2.5-flash-native-audio")

    def test_realtime_voice_service_falls_back_from_text_models_to_native_audio(self):
        """When a text model (e.g. gemini-2.5-flash or gemini-3.8-flash) is passed
        to _resolve_google_settings for AgentPlatform, it must safely fall back
        to the canonical realtime model (gemini-live-2.5-flash-native-audio)."""
        cfg = self._config(api_keys={
            "vertex_api_key": "AQ-mock-vertex-key",
            "google_api_key": "AQ-mock-google-key",
        })
        service = RealtimeVoiceService(cfg)
        # 1. Text model under AgentPlatform
        resolved_ap = service._resolve_google_settings("gemini-2.5-flash", provider="AgentPlatform")
        self.assertEqual(resolved_ap["model"], "gemini-live-2.5-flash-native-audio")

        # 2. None model under AgentPlatform
        resolved_none = service._resolve_google_settings(None, provider="AgentPlatform")
        self.assertEqual(resolved_none["model"], "gemini-live-2.5-flash-native-audio")

        # 3. Text model under Google
        resolved_google = service._resolve_google_settings("gemini-2.5-flash", provider="Google")
        self.assertEqual(resolved_google["model"], "gemini-2.5-flash-native-audio-preview-12-2025")

    def test_service_account_discovery_prefers_explicit_path(self):
        """The router pre-check and the provider must agree on what counts as
        configured credentials, so they share this one resolver."""
        import os
        from unittest.mock import patch as _patch

        from services.realtime_constants import (
            resolve_agent_platform_service_account_file,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            explicit = Path(tmp_dir) / "sa-explicit.json"
            explicit.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")
            from_env = Path(tmp_dir) / "sa-env.json"
            from_env.write_text(json.dumps({"type": "service_account"}), encoding="utf-8")

            with _patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": ""}, clear=False):
                resolved = resolve_agent_platform_service_account_file(str(explicit))
                self.assertEqual(Path(resolved), explicit.resolve())

            # GOOGLE_APPLICATION_CREDENTIALS wins over the config setting.
            with _patch.dict(
                os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": str(from_env)}, clear=False
            ):
                resolved = resolve_agent_platform_service_account_file(str(explicit))
                self.assertEqual(Path(resolved), from_env.resolve())

            # A path that does not exist must not be returned as-is; it falls
            # through to discovery (which may legitimately find nothing).
            missing = str(Path(tmp_dir) / "nope.json")
            with _patch.dict(os.environ, {"GOOGLE_APPLICATION_CREDENTIALS": ""}, clear=False):
                resolved = resolve_agent_platform_service_account_file(missing)
                self.assertNotEqual(resolved, missing)

    def test_provider_and_router_share_the_same_credential_resolver(self):
        """If these ever diverge again, the pre-check starts rejecting sessions
        the provider could have served (or vice versa)."""
        from services import realtime_constants, realtime_google_provider

        self.assertIs(
            realtime_google_provider.resolve_agent_platform_service_account_file,
            realtime_constants.resolve_agent_platform_service_account_file,
        )

    def test_build_realtime_instructions_accepts_initial_memory_context_kwarg(self):
        """_build_realtime_instructions must accept memory_context, initial_memory_context
        kwarg, or positional args without raising unexpected keyword argument errors."""
        service = RealtimeVoiceService(self._config())

        # Positional
        inst1 = service._build_realtime_instructions("- user likes tea")
        self.assertIn("user likes tea", inst1)

        # initial_memory_context kwarg
        inst2 = service._build_realtime_instructions(initial_memory_context="- user likes coffee")
        self.assertIn("user likes coffee", inst2)

        # memory_context kwarg
        inst3 = service._build_realtime_instructions(memory_context="- user likes water")
        self.assertIn("user likes water", inst3)

        # Empty / no args
        inst4 = service._build_realtime_instructions()
        self.assertIn("Memory & Tool Calling Rules", inst4)


if __name__ == "__main__":
    unittest.main()
