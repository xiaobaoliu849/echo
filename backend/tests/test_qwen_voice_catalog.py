import unittest
from unittest.mock import AsyncMock, patch

from services.qwen_voice_service import QwenModelUnavailable, QwenVoiceService


class QwenVoiceCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_unified_catalog_fallback_preserves_page_and_filters_clones(self):
        service = QwenVoiceService()
        rows = [
            {"voice_id": "qwen-audio-3.1-tts-plus-vd-reader-123"},
            {"voice_id": "qwen-audio-3.1-tts-plus-vc-reader-456"},
        ]
        request = AsyncMock(side_effect=[QwenModelUnavailable(), {"output": {"voice_list": rows}}])
        with patch.object(service, "_request", request):
            result = await service.list_voices(voice_type="voice_design", page_index=2, page_size=20)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["voices"][0]["voice"], rows[0]["voice_id"])
        self.assertEqual(result["voices"][0]["target_model"], "qwen-audio-3.1-tts-plus")
        self.assertEqual(request.await_args.args[0], {
            "model": "voice-enrollment",
            "input": {"action": "list_voice", "page_index": 2, "page_size": 20},
        })
