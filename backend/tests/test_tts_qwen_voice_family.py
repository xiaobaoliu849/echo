"""Qwen TTS voice-family compatibility tests.

qwen-audio-3.0-tts-* models use the longan voice family while qwen3-tts-*
models use the Cherry/Ono Anna family; mixing them makes the DashScope SDK
return None audio. These tests cover the guardrails that prevent that.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.tts_service import (
    DEFAULT_QWEN_AUDIO_31_TTS_VOICE,
    DEFAULT_QWEN_AUDIO_TTS_NEXT_VOICE,
    DEFAULT_QWEN_AUDIO_TTS_VOICE,
    QWEN_AUDIO_31_TTS_VOICES,
    QWEN_AUDIO_TTS_NEXT_VOICES,
    QWEN_AUDIO_TTS_VOICES,
    QWEN_FLASH_VOICES,
    TTS_ENGINE_QWEN_FLASH,
    TTSService,
    is_qwen_audio_31_tts_model,
    is_qwen_audio_tts_model,
    is_qwen_audio_tts_next_model,
)


class QwenAudioTtsModelDetectionTests(unittest.TestCase):
    def test_is_qwen_audio_tts_model(self) -> None:
        self.assertTrue(is_qwen_audio_tts_model("qwen-audio-3.0-tts-flash"))
        self.assertTrue(is_qwen_audio_tts_model("qwen-audio-3.0-tts-plus"))
        self.assertTrue(is_qwen_audio_tts_model("qwen-audio-3.1-tts-flash"))
        self.assertTrue(is_qwen_audio_31_tts_model("qwen-audio-3.1-tts-flash"))
        self.assertFalse(is_qwen_audio_31_tts_model("qwen-audio-3.0-tts-flash"))
        self.assertTrue(is_qwen_audio_tts_next_model("qwen-audio-3.1-tts-next"))
        self.assertFalse(is_qwen_audio_tts_next_model("qwen-audio-3.1-tts-flash"))
        self.assertFalse(is_qwen_audio_31_tts_model("qwen-audio-3.1-tts-next"))
        self.assertFalse(is_qwen_audio_tts_model("qwen-audio-3.1-tts-next"))
        self.assertFalse(is_qwen_audio_tts_model("qwen3-tts-flash-2025-11-27"))
        self.assertFalse(is_qwen_audio_tts_model("qwen3-tts-flash"))
        self.assertFalse(is_qwen_audio_tts_model(None))
        self.assertFalse(is_qwen_audio_tts_model(""))


class QwenVoiceResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = TTSService()

    def test_rejects_flash_voice_on_audio_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "不兼容"):
            self.service._resolve_qwen_voice_for_model("Ono Anna", "qwen-audio-3.0-tts-flash")
        with self.assertRaisesRegex(ValueError, "不兼容"):
            self.service._resolve_qwen_voice_for_model("Ono Anna", "qwen-audio-3.1-tts-flash")

    def test_rejects_longan_voice_on_flash_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "不兼容"):
            self.service._resolve_qwen_voice_for_model("longanhuan_v3.6", "qwen3-tts-flash-2025-11-27")
        with self.assertRaisesRegex(ValueError, "不兼容"):
            self.service._resolve_qwen_voice_for_model("longanhuan_v3.1", "qwen3-tts-flash-2025-11-27")

    def test_passes_compatible_voices(self) -> None:
        self.assertEqual(
            self.service._resolve_qwen_voice_for_model("longanhuan_v3.6", "qwen-audio-3.0-tts-flash"),
            "longanhuan_v3.6",
        )
        self.assertEqual(
            self.service._resolve_qwen_voice_for_model("longanhuan_v3.1", "qwen-audio-3.1-tts-flash"),
            "longanhuan_v3.1",
        )
        self.assertEqual(
            self.service._resolve_qwen_voice_for_model("yuxiaoyun_v3.1", "qwen-audio-3.1-tts-flash"),
            "yuxiaoyun_v3.1",
        )
        self.assertEqual(
            self.service._resolve_qwen_voice_for_model("longanhuan_v3.6", "qwen-audio-3.1-tts-flash"),
            "longanhuan_v3.1",
        )
        self.assertEqual(
            self.service._resolve_qwen_voice_for_model("Ono Anna", "qwen3-tts-flash-2025-11-27"),
            "Ono Anna",
        )

    def test_passes_custom_cloned_voices_through(self) -> None:
        self.assertEqual(
            self.service._resolve_qwen_voice_for_model("qwen3-tts-vc-abc123", "qwen-audio-3.0-tts-flash"),
            "qwen3-tts-vc-abc123",
        )
        self.assertEqual(
            self.service._resolve_qwen_voice_for_model("qwen3-tts-vc-abc123", "qwen-audio-3.1-tts-flash"),
            "qwen3-tts-vc-abc123",
        )
        self.assertEqual(
            self.service._resolve_qwen_voice_for_model("qwen3-tts-vd-xyz", "qwen3-tts-flash-2025-11-27"),
            "qwen3-tts-vd-xyz",
        )

    def test_tts_next_voice_resolution(self) -> None:
        self.assertEqual(
            self.service._resolve_qwen_voice_for_model(None, "qwen-audio-3.1-tts-next"),
            DEFAULT_QWEN_AUDIO_TTS_NEXT_VOICE,
        )
        self.assertEqual(
            self.service._resolve_qwen_voice_for_model("tts-next-narrator", "qwen-audio-3.1-tts-next"),
            "tts-next-narrator",
        )
        with self.assertRaisesRegex(ValueError, "不兼容"):
            self.service._resolve_qwen_voice_for_model("Ono Anna", "qwen-audio-3.1-tts-next")

    def test_detect_engine_by_voice_recognizes_longan_family(self) -> None:
        self.assertEqual(self.service.detect_engine_by_voice("longanhuan_v3.6"), TTS_ENGINE_QWEN_FLASH)
        self.assertEqual(self.service.detect_engine_by_voice("longanhuan_v3.1"), TTS_ENGINE_QWEN_FLASH)
        self.assertEqual(self.service.detect_engine_by_voice("yuxiaoyun_v3.1"), TTS_ENGINE_QWEN_FLASH)
        self.assertEqual(self.service.detect_engine_by_voice("loongjohn"), TTS_ENGINE_QWEN_FLASH)
        self.assertEqual(self.service.detect_engine_by_voice("tts-next-auto"), TTS_ENGINE_QWEN_FLASH)


class QwenVoiceListingTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_voices_filters_by_qwen_model_family(self) -> None:
        service = TTSService()

        audio_voices = await service.list_voices(engine=TTS_ENGINE_QWEN_FLASH, model="qwen-audio-3.0-tts-flash")
        audio_names = {v["name"] for v in audio_voices}
        self.assertEqual(audio_names, {v["name"] for v in QWEN_AUDIO_TTS_VOICES})
        self.assertNotIn("Ono Anna", audio_names)

        audio_31_voices = await service.list_voices(engine=TTS_ENGINE_QWEN_FLASH, model="qwen-audio-3.1-tts-flash")
        audio_31_names = {v["name"] for v in audio_31_voices}
        self.assertEqual(audio_31_names, {v["name"] for v in QWEN_AUDIO_31_TTS_VOICES})
        self.assertIn("longanhuan_v3.1", audio_31_names)
        self.assertIn("yuxiaoyun_v3.1", audio_31_names)
        self.assertNotIn("Ono Anna", audio_31_names)

        audio_next_voices = await service.list_voices(engine=TTS_ENGINE_QWEN_FLASH, model="qwen-audio-3.1-tts-next")
        audio_next_names = {v["name"] for v in audio_next_voices}
        self.assertEqual(audio_next_names, {v["name"] for v in QWEN_AUDIO_TTS_NEXT_VOICES})
        self.assertIn("tts-next-auto", audio_next_names)
        self.assertNotIn("Ono Anna", audio_next_names)
        self.assertNotIn("longanhuan_v3.1", audio_next_names)

        flash_voices = await service.list_voices(engine=TTS_ENGINE_QWEN_FLASH, model="qwen3-tts-flash-2025-11-27")
        flash_names = {v["name"] for v in flash_voices}
        self.assertEqual(flash_names, {v["name"] for v in QWEN_FLASH_VOICES})
        self.assertNotIn("longanhuan_v3.6", flash_names)
        self.assertNotIn("longanhuan_v3.1", flash_names)
        self.assertNotIn("tts-next-auto", flash_names)

        # No model -> legacy behavior (qwen3-tts family)
        default_voices = await service.list_voices(engine=TTS_ENGINE_QWEN_FLASH)
        self.assertEqual({v["name"] for v in default_voices}, flash_names)


class QwenGenerateAudioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.service = TTSService(output_dir=Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    async def test_defaults_to_longan_voice_for_audio_model(self) -> None:
        captured: dict[str, str] = {}

        async def fake_generate(text: str, voice: str, path: Path, model: str | None = None) -> None:
            captured["voice"] = voice
            captured["model"] = model or ""
            path.write_bytes(b"fake-audio")

        with patch.object(self.service, "_generate_qwen_flash_audio", new=fake_generate):
            result = await self.service.generate_audio(
                "你好", voice=None, engine=TTS_ENGINE_QWEN_FLASH, model="qwen-audio-3.0-tts-flash"
            )

        self.assertEqual(captured["voice"], DEFAULT_QWEN_AUDIO_TTS_VOICE)
        self.assertEqual(result.voice, DEFAULT_QWEN_AUDIO_TTS_VOICE)

    async def test_mismatched_voice_model_raises_actionable_error(self) -> None:
        # Validation happens before any network call; patch the key lookup so
        # the test does not depend on local config.
        with patch.object(self.service, "_dashscope_key", return_value="sk-test"):
            with self.assertRaisesRegex(ValueError, "不兼容"):
                await self.service.generate_audio(
                    "你好", voice="Ono Anna", engine=TTS_ENGINE_QWEN_FLASH, model="qwen-audio-3.0-tts-flash"
                )

    async def test_none_audio_raises_clear_error(self) -> None:
        import sys
        import types

        class FakeSynthesizer:
            def __init__(self, model: str, voice: str) -> None:
                _ = (model, voice)

            def call(self, text: str):
                _ = text
                return None  # SDK failure mode: returns None instead of bytes

            def get_last_request_id(self) -> str:
                return "req-123"

        fake_dashscope = types.ModuleType("dashscope")
        fake_audio = types.ModuleType("dashscope.audio")
        fake_tts_v2 = types.ModuleType("dashscope.audio.tts_v2")
        fake_tts_v2.SpeechSynthesizer = FakeSynthesizer  # type: ignore[attr-defined]
        fake_audio.tts_v2 = fake_tts_v2  # type: ignore[attr-defined]
        fake_dashscope.audio = fake_audio  # type: ignore[attr-defined]

        modules = {
            "dashscope": fake_dashscope,
            "dashscope.audio": fake_audio,
            "dashscope.audio.tts_v2": fake_tts_v2,
        }
        with patch.dict(sys.modules, modules):
            with patch.object(self.service, "_dashscope_key", return_value="sk-test"):
                with self.assertRaisesRegex(RuntimeError, "未返回音频数据.*req-123"):
                    await self.service._generate_qwen_flash_audio(
                        "你好",
                        "longanhuan_v3.6",
                        Path(self._tmp.name) / "out.mp3",
                        model="qwen-audio-3.0-tts-flash",
                    )

    async def test_defaults_to_tts_next_auto_voice(self) -> None:
        captured: dict[str, str] = {}

        async def fake_generate(text: str, voice: str | None, path: Path, model: str | None = None) -> None:
            captured["voice"] = voice or ""
            captured["model"] = model or ""
            path.write_bytes(b"fake-audio")

        with patch.object(self.service, "_generate_qwen_tts_next_audio", new=fake_generate):
            result = await self.service.generate_audio(
                "测试旁白", voice=None, engine=TTS_ENGINE_QWEN_FLASH, model="qwen-audio-3.1-tts-next"
            )

        self.assertEqual(captured["voice"], DEFAULT_QWEN_AUDIO_TTS_NEXT_VOICE)
        self.assertEqual(result.voice, DEFAULT_QWEN_AUDIO_TTS_NEXT_VOICE)

    async def test_generate_qwen_tts_next_audio_downloads_audio(self) -> None:
        import httpx

        out_path = Path(self._tmp.name) / "next_out.wav"
        post_called = False
        get_called = False

        async def fake_post(client_self, endpoint: str, **kwargs):
            nonlocal post_called
            post_called = True
            json_payload = kwargs.get("json", {})
            self.assertEqual(json_payload.get("model"), "qwen-audio-3.1-tts-next")
            self.assertIn("[旁白/叙事风格]", json_payload.get("input", {}).get("text_prompt", ""))
            resp = httpx.Response(
                200,
                json={"output": {"audio": {"url": "https://fake.url/audio.wav"}}, "request_id": "req-next-1"},
                request=httpx.Request("POST", endpoint),
            )
            return resp

        async def fake_get(client_self, url: str, **kwargs):
            nonlocal get_called
            get_called = True
            self.assertEqual(url, "https://fake.url/audio.wav")
            return httpx.Response(200, content=b"RIFFwavdata", request=httpx.Request("GET", url))

        with patch.object(self.service, "_dashscope_key", return_value="sk-test"):
            with patch("httpx.AsyncClient.post", new=fake_post), patch("httpx.AsyncClient.get", new=fake_get):
                await self.service._generate_qwen_tts_next_audio(
                    "一段优美的故事", "tts-next-narrator", out_path, model="qwen-audio-3.1-tts-next"
                )

        self.assertTrue(post_called)
        self.assertTrue(get_called)
        self.assertEqual(out_path.read_bytes(), b"RIFFwavdata")


if __name__ == "__main__":
    unittest.main()
