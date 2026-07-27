from __future__ import annotations

import unittest

from routers.settings import (
    DASHSCOPE_MODEL_LIST_SUPPLEMENTS,
    _filter_dashscope_models,
    _is_retired_dashscope_model,
    _is_tts_model_id,
    _merge_dashscope_supplements,
)
from services.settings_service import SettingsService


class FilterDashScopeModelsTests(unittest.TestCase):
    def test_keeps_current_livetranslate_realtime(self) -> None:
        # The undated production alias must survive the filter (no date suffix to strip,
        # and the "-flash-" off-topic keyword is overridden for voice/realtime models).
        filtered = _filter_dashscope_models(["qwen3.5-livetranslate-flash-realtime"])
        self.assertIn("qwen3.5-livetranslate-flash-realtime", filtered)

    def test_drops_legacy_qwen3_livetranslate_keeps_qwen35(self) -> None:
        # VoiceSpirit ships only the newest LiveTranslate model; the legacy
        # qwen3-livetranslate series must be filtered out (dated or not), while
        # qwen3.5-livetranslate-flash-realtime is kept.
        filtered = _filter_dashscope_models(
            [
                "qwen3-livetranslate-flash",
                "qwen3-livetranslate-flash-realtime",
                "qwen3.5-livetranslate-flash-realtime",
            ]
        )
        self.assertNotIn("qwen3-livetranslate-flash", filtered)
        self.assertNotIn("qwen3-livetranslate-flash-realtime", filtered)
        self.assertIn("qwen3.5-livetranslate-flash-realtime", filtered)

    def test_drops_date_snapshots_and_off_topic_families(self) -> None:
        noisy = [
            "qwen3-livetranslate-flash-realtime-2025-09-22",  # legacy + date -> drop
            "qwen2.5-72b-instruct",                            # raw checkpoint -> drop
            "qwen-vl-ocr",                                     # off-topic -> drop
            "qwen-coder-plus",                                 # off-topic -> drop
            "deepseek-r1",                                     # non-DashScope family -> drop
            "qwen-plus",                                       # product alias -> keep
        ]
        filtered = _filter_dashscope_models(noisy)
        self.assertIn("qwen-plus", filtered)
        for dropped in noisy[:-1]:
            self.assertNotIn(dropped, filtered)


class SupplementClassificationTests(unittest.TestCase):
    def test_tts_supplements_are_classified_as_tts(self) -> None:
        tts_supplements = [
            "qwen-audio-3.0-tts-plus",
            "qwen-audio-3.0-tts-flash",
            "qwen3-tts-flash-2025-11-27",
        ]
        for model in tts_supplements:
            self.assertIn(model, DASHSCOPE_MODEL_LIST_SUPPLEMENTS)
            self.assertTrue(_is_tts_model_id(model), model)

    def test_legacy_tts_models_are_not_supplemented(self) -> None:
        # Retired generations (cosyvoice/sambert/qwen-tts-v2) were removed from
        # the curated list; only qwen-audio-3.0-tts and qwen3-tts-flash ship.
        for legacy in ("cosyvoice-v2-1.5", "cosyvoice-v1", "sambert-zhichu-v1", "qwen-tts-v2"):
            self.assertNotIn(legacy, DASHSCOPE_MODEL_LIST_SUPPLEMENTS)

    def test_livetranslate_and_omni_supplements_are_chat(self) -> None:
        chat_supplements = [
            "qwen3.5-livetranslate-flash-realtime",
            "qwen3.5-omni-plus-realtime-2026-03-15",
        ]
        for model in chat_supplements:
            self.assertIn(model, DASHSCOPE_MODEL_LIST_SUPPLEMENTS)
            self.assertFalse(_is_tts_model_id(model), model)

    def test_non_realtime_omni_flash_is_not_supplemented(self) -> None:
        # qwen3-omni-flash-2025-12-01 is a multimodal but NOT realtime model;
        # it must not be re-added to the chat model list.
        self.assertNotIn("qwen3-omni-flash-2025-12-01", DASHSCOPE_MODEL_LIST_SUPPLEMENTS)


class MergeDashScopeSupplementsTests(unittest.TestCase):
    def test_routes_supplements_into_correct_sublists(self) -> None:
        entry: dict = {"available": ["qwen-plus"], "tts_available": ["cosyvoice-v1"]}
        _merge_dashscope_supplements(entry)

        # Chat/realtime supplements land in "available".
        self.assertIn("qwen3.5-livetranslate-flash-realtime", entry["available"])
        self.assertIn("qwen3.5-omni-plus-realtime-2026-03-15", entry["available"])
        # TTS supplements land in "tts_available", never in chat "available".
        self.assertIn("qwen-audio-3.0-tts-plus", entry["tts_available"])
        self.assertIn("qwen3-tts-flash-2025-11-27", entry["tts_available"])
        for model in entry["available"]:
            self.assertFalse(_is_tts_model_id(model), f"{model} leaked into chat available")

    def test_dedupes_and_preserves_existing_order(self) -> None:
        entry: dict = {
            "available": ["qwen-plus", "qwen3.5-livetranslate-flash-realtime"],
            "tts_available": ["cosyvoice-v1"],
        }
        _merge_dashscope_supplements(entry)
        # Pre-existing entries keep their positions; no duplicates introduced.
        self.assertEqual(entry["available"][0], "qwen-plus")
        self.assertEqual(entry["available"][1], "qwen3.5-livetranslate-flash-realtime")
        self.assertEqual(entry["available"].count("qwen3.5-livetranslate-flash-realtime"), 1)
        self.assertEqual(entry["tts_available"].count("cosyvoice-v1"), 1)

    def test_missing_tts_available_field_is_created(self) -> None:
        entry: dict = {"available": ["qwen-plus"]}
        _merge_dashscope_supplements(entry)
        self.assertIsInstance(entry["tts_available"], list)
        self.assertIn("qwen-audio-3.0-tts-flash", entry["tts_available"])


class GetSettingsRefilterIntegrationTests(unittest.TestCase):
    """Replicates the GET /settings re-filter path: filter first, then merge supplements."""

    def test_qwen35_livetranslate_recovered_even_when_absent_from_config(self) -> None:
        # The original bug: config.json persisted a list WITHOUT the undated qwen3.5
        # livetranslate alias (only dated snapshots the filter drops). The old path did
        # not merge supplements, so qwen3.5 never reappeared. The fixed path must restore it.
        raw_avail = [
            "qwen-plus",
            "qwen-max",
            "qwen3-livetranslate-flash",
            "qwen3-livetranslate-flash-realtime",
            "qwen3.5-livetranslate-flash-realtime-2026-05-19",  # dated -> dropped by filter
        ] + [f"qwen2.5-{n}b-instruct" for n in range(7, 73)]  # pad past the >30 re-filter gate

        entry: dict = {"available": list(raw_avail), "tts_available": []}
        # Mirror settings.py get_settings(): filter when bloated, then always merge.
        if len(entry["available"]) > 30:
            entry["available"] = _filter_dashscope_models(entry["available"])
        _merge_dashscope_supplements(entry)

        self.assertIn("qwen3.5-livetranslate-flash-realtime", entry["available"])
        # Legacy qwen3-livetranslate is filtered out; only the newest model ships.
        self.assertNotIn("qwen3-livetranslate-flash-realtime", entry["available"])
        self.assertLess(len(entry["available"]), 30)
        self.assertNotIn("qwen2.5-72b-instruct", entry["available"])


class RetiredDashScopeModelTests(unittest.TestCase):
    def test_legacy_qwen3_omni_and_livetranslate_are_retired(self) -> None:
        for legacy in (
            "qwen3-omni-flash-2025-12-01",
            "qwen3-omni-flash",
            "qwen3-omni-flash-realtime",
            "qwen3-livetranslate-flash-realtime",
        ):
            self.assertTrue(_is_retired_dashscope_model(legacy), legacy)

    def test_current_qwen35_and_audio_models_are_not_retired(self) -> None:
        for current in (
            "qwen3.5-omni-plus-realtime",
            "qwen3.5-omni-plus-realtime-2026-03-15",
            "qwen3.5-omni-flash-realtime",
            "qwen3.5-livetranslate-flash-realtime",
            "qwen-audio-3.0-realtime-plus",
            "qwen-plus",
        ):
            self.assertFalse(_is_retired_dashscope_model(current), current)

    def test_filter_drops_legacy_qwen3_omni_keeps_qwen35(self) -> None:
        filtered = _filter_dashscope_models(
            [
                "qwen3-omni-flash-2025-12-01",
                "qwen3-omni-flash-realtime",
                "qwen3.5-omni-plus-realtime",
                "qwen-plus",
            ]
        )
        self.assertNotIn("qwen3-omni-flash-2025-12-01", filtered)
        self.assertNotIn("qwen3-omni-flash-realtime", filtered)
        self.assertIn("qwen3.5-omni-plus-realtime", filtered)
        self.assertIn("qwen-plus", filtered)


class GetSettingsEnabledSanitizationTests(unittest.TestCase):
    """The GET /settings path must strip retired legacy models from the persisted
    DashScope enabled/available lists so they no longer reach the model picker."""

    def test_legacy_models_removed_from_enabled_and_available_on_load(self) -> None:
        import asyncio
        import json
        import tempfile
        from pathlib import Path

        import routers.settings as settings_router
        from services.config_loader import BackendConfig

        with tempfile.TemporaryDirectory() as tmp_dir:
            config_path = Path(tmp_dir) / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "default_models": {
                            "DashScope": {
                                "default": "",
                                "available": ["qwen-plus", "qwen3-omni-flash-2025-12-01"],
                                "enabled": [
                                    "qwen3-omni-flash-2025-12-01",
                                    "qwen3.5-omni-plus-realtime-2026-03-15",
                                    "qwen-audio-3.0-realtime-plus",
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            test_service = SettingsService(config=BackendConfig(config_path))
            original_service = settings_router.settings_service
            settings_router.settings_service = test_service
            try:
                response = asyncio.run(settings_router.get_settings())
            finally:
                settings_router.settings_service = original_service

            ds = response.settings["default_models"]["DashScope"]
            # Legacy model stripped from both lists; current models preserved.
            self.assertNotIn("qwen3-omni-flash-2025-12-01", ds["enabled"])
            self.assertNotIn("qwen3-omni-flash-2025-12-01", ds["available"])
            self.assertIn("qwen3.5-omni-plus-realtime-2026-03-15", ds["enabled"])
            self.assertIn("qwen-audio-3.0-realtime-plus", ds["enabled"])
            self.assertIn("qwen-plus", ds["available"])


if __name__ == "__main__":
    unittest.main()
