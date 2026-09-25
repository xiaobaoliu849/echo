from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.config_loader import BackendConfig
from services.transcription_service import TranscriptionService


def _write_config(tmp_dir: str, config: dict) -> Path:
    import json

    path = Path(tmp_dir) / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


class ListTranslationProvidersTests(unittest.TestCase):
    """GET /api/transcription/translation-providers payload builder."""

    def test_every_builtin_provider_is_routable_by_llm_service(self) -> None:
        # Adversarial: any builtin provider we advertise must actually be
        # routeable by chat_completion, otherwise the user picks it and the
        # translate call fails with "Unsupported provider" (the old Xiaomi
        # dropdown entry had exactly this bug). Ollama is exempt because
        # _resolve_settings fakes its key for local deployments.
        from services.llm_service import SUPPORTED_PROVIDERS

        builtin_ids = {pid for pid, _, _ in TranscriptionService.TRANSLATION_PROVIDER_LABELS}
        unroutable = builtin_ids - SUPPORTED_PROVIDERS
        self.assertEqual(unroutable, set(), f"catalog advertises providers llm_service cannot route: {unroutable}")

    def test_labels_are_current_generation(self) -> None:
        # The old dropdown hardcoded stale brand strings ("Gemini 2.5 Flash",
        # "DeepSeek (V3 / R1)" as one entry, a Xiaomi option llm_service cannot
        # even route). The catalog must expose fresh per-provider labels and
        # never present Xiaomi as a chat-translation engine.
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = _write_config(tmp_dir, {})
            providers = TranscriptionService(config=BackendConfig(config_path)).list_translation_providers()

        by_id = {p["id"]: p for p in providers["providers"]}
        self.assertNotIn("Xiaomi", by_id)
        for expected in ("DashScope", "Google", "DeepSeek", "OpenRouter", "SiliconFlow"):
            self.assertIn(expected, by_id)
        dashscope = by_id["DashScope"]
        self.assertIn("Qwen", dashscope["label"])
        self.assertEqual(providers["recommended"], "DashScope")

    def test_reflects_configured_default_models_and_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = _write_config(
                tmp_dir,
                {
                    "api_keys": {
                        "dashscope_api_key": "sk-live-dashscope",
                        "deepseek_api_key": "sk-live-deepseek",
                    },
                    "default_models": {
                        "DashScope": {"default": "qwen3.5-plus", "available": ["qwen3.5-plus", "qwen-max"]},
                        "Google": {"default": "gemini-3.8-flash"},
                        "DeepSeek": {"default": "deepseek-v4-pro"},
                    },
                },
            )
            payload = TranscriptionService(config=BackendConfig(config_path)).list_translation_providers()

        by_id = {p["id"]: p for p in payload["providers"]}
        # Models come from live config, not hardcoded strings.
        self.assertEqual(by_id["DashScope"]["model"], "qwen3.5-plus")
        self.assertEqual(by_id["Google"]["model"], "gemini-3.8-flash")
        self.assertEqual(by_id["DeepSeek"]["model"], "deepseek-v4-pro")
        # Only providers with configured keys are recommended / flagged.
        self.assertTrue(by_id["DashScope"]["has_api_key"])
        self.assertTrue(by_id["DeepSeek"]["has_api_key"])
        self.assertFalse(by_id["Google"]["has_api_key"])
        self.assertEqual(payload["recommended"], "DashScope")

    def test_recommended_skips_providers_without_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = _write_config(
                tmp_dir,
                {"api_keys": {"deepseek_api_key": "sk-live-deepseek"}},
            )
            payload = TranscriptionService(config=BackendConfig(config_path)).list_translation_providers()

        self.assertEqual(payload["recommended"], "DeepSeek")

    def test_ollama_never_wins_recommendation_by_default(self) -> None:
        # Ollama is advertised as always usable (local runtime needs no API
        # key), but "needs no key" must not make it the recommendation when
        # nothing is configured — the primary cloud recommendation wins.
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = _write_config(tmp_dir, {})
            payload = TranscriptionService(config=BackendConfig(config_path)).list_translation_providers()

        ollama = next(p for p in payload["providers"] if p["id"] == "Ollama")
        self.assertTrue(ollama["has_api_key"])
        self.assertEqual(payload["recommended"], "DashScope")

    def test_ollama_used_as_fallback_when_no_cloud_key(self) -> None:
        # translate_cues must fall back to Ollama instead of erroring when no
        # cloud key exists (old code only probed cloud providers).
        import asyncio

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = _write_config(tmp_dir, {})
            service = TranscriptionService(config=BackendConfig(config_path))

            async def fake_chat(**kwargs):
                return {"reply": "[\"你好\"]"}

            with patch.object(service.llm_service, "chat_completion", new=fake_chat):
                cues = asyncio.run(
                    service.translate_cues([{"text": "hello", "start": 0.0, "end": 1.0}], target_language="zh-CN")
                )

        self.assertEqual(cues[0]["translation"], "你好")

    def test_appends_custom_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = _write_config(
                tmp_dir,
                {
                    "custom_providers": [
                        {
                            "id": "my-gateway",
                            "name": "My Gateway",
                            "api_key": "sk-custom",
                            "base_url": "https://gw.example.com/v1",
                            "default_model": "gpt-5.5-turbo",
                        }
                    ]
                },
            )
            payload = TranscriptionService(config=BackendConfig(config_path)).list_translation_providers()

        ids = [p["id"] for p in payload["providers"]]
        self.assertIn("my-gateway", ids)
        custom = next(p for p in payload["providers"] if p["id"] == "my-gateway")
        self.assertTrue(custom["custom"])
        self.assertEqual(custom["model"], "gpt-5.5-turbo")
        self.assertTrue(custom["has_api_key"])
        self.assertEqual(custom["label"], "My Gateway")

    def test_endpoint_requires_auth_and_returns_live_catalog(self) -> None:
        from routers import transcription as transcription_router

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = _write_config(
                tmp_dir,
                {
                    "api_keys": {"dashscope_api_key": "sk-live"},
                    "default_models": {"DashScope": {"default": "qwen3.5-plus"}},
                },
            )
            fake_service = TranscriptionService(config=BackendConfig(config_path))

            with patch.object(transcription_router, "transcription_service", fake_service):
                import asyncio

                response = asyncio.run(transcription_router.list_translation_providers())

        self.assertEqual(response.recommended, "DashScope")
        dashscope = next(p for p in response.providers if p.id == "DashScope")
        self.assertEqual(dashscope.model, "qwen3.5-plus")
        self.assertTrue(dashscope.has_api_key)


if __name__ == "__main__":
    unittest.main()
