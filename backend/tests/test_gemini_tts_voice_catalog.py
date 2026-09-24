from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from services.tts_service import TTSService


@pytest.mark.asyncio
async def test_gemini_tts_catalog_includes_stored_custom_voice_ids_and_display_names(tmp_path: Path):
    service = TTSService(output_dir=tmp_path)
    stored_voices = [
        {"id": "voice_xiao_123", "type": "replicated", "display_name": "小晓"},
        {"id": "voice_narrator_456", "type": "prompted", "display_name": "Narrator"},
        {"id": "Puck", "type": "prebuilt", "display_name": "Puck"},
    ]

    with patch("services.gemini_voice_service.GeminiVoiceService.list_stored_voices", new=AsyncMock(return_value=stored_voices)):
        voices = await service.list_voices(engine="gemini")
        chinese_voices = await service.list_voices(engine="gemini", locale="zh-CN")

    cloned_voice = next(voice for voice in voices if voice["name"] == "voice_xiao_123")
    assert cloned_voice["short_name"] == "小晓"
    assert cloned_voice["gender"] == "Custom"
    assert cloned_voice["locale"] == "multi"
    assert "Puck" in [voice["name"] for voice in voices]
    assert "voice_narrator_456" in [voice["name"] for voice in voices]

    assert "voice_xiao_123" in [voice["name"] for voice in chinese_voices]
