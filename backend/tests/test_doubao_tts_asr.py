import unittest
from unittest.mock import AsyncMock, patch
from services.tts_service import TTSService, TTS_ENGINE_DOUBAO
from services.transcription_service import TranscriptionService
from services.doubao_tts_provider import is_doubao_voice, DOUBAO_VOICES
from services.doubao_asr_provider import _build_header, _build_full_client_request, _build_audio_request, _parse_server_error


class TestDoubaoTTS(unittest.IsolatedAsyncioTestCase):
    def test_is_doubao_voice(self):
        self.assertTrue(is_doubao_voice("zh_female_vv_uranus_bigtts"))
        self.assertTrue(is_doubao_voice("custom_jupiter_voice"))
        self.assertTrue(is_doubao_voice("custom_uranus_voice"))
        self.assertFalse(is_doubao_voice("zh-CN-XiaoxiaoNeural"))

    def test_detect_engine_by_voice_doubao(self):
        service = TTSService()
        engine = service.detect_engine_by_voice("zh_female_vv_uranus_bigtts")
        self.assertEqual(engine, TTS_ENGINE_DOUBAO)

    @patch("services.tts_service.doubao_tts_synthesize", new_callable=AsyncMock)
    async def test_generate_doubao_audio(self, mock_synthesize):
        import uuid
        mock_synthesize.return_value = b"FAKE_AUDIO_DATA"
        service = TTSService()
        service._doubao_settings = lambda: ("fake_token", "fake_appid", "volcano_tts")
        
        def fake_write(path, data):
            path.write_bytes(data)

        unique_text = f"测试文本_{uuid.uuid4().hex}"
        with patch.object(service, "_atomic_write_bytes", side_effect=fake_write):
            result = await service.generate_audio(unique_text, voice="zh_female_vv_uranus_bigtts", engine="doubao")
        self.assertEqual(result.engine, "doubao")
        self.assertEqual(result.voice, "zh_female_vv_uranus_bigtts")
        mock_synthesize.assert_called_once()

    async def test_list_voices_doubao(self):
        service = TTSService()
        voices = await service.list_voices(engine="doubao")
        self.assertEqual(len(voices), len(DOUBAO_VOICES))


class TestDoubaoASR(unittest.IsolatedAsyncioTestCase):
    def test_binary_protocol_helpers(self):
        header = _build_header(msg_type=1, flags=0, serialization=1, compression=1)
        self.assertEqual(len(header), 4)

        full_req = _build_full_client_request({"test": "data"})
        self.assertGreater(len(full_req), 8)

        audio_req = _build_audio_request(b"12345", is_last=True)
        self.assertGreater(len(audio_req), 8)

    def test_parse_server_error(self):
        import struct
        hdr = _build_header(15, 0, 0, 0)
        err_code_bytes = struct.pack("!I", 45000001)
        msg = "Invalid params".encode("utf-8")
        msg_len_bytes = struct.pack("!I", len(msg))
        
        frame = hdr + err_code_bytes + msg_len_bytes + msg
        code, message = _parse_server_error(frame)
        self.assertEqual(code, 45000001)
        self.assertEqual(message, "Invalid params")

    @patch("services.transcription_service.doubao_asr_transcribe_file", new_callable=AsyncMock)
    async def test_transcribe_with_doubao(self, mock_transcribe):
        mock_transcribe.return_value = {"text": "转写结果", "duration_seconds": 2.5, "words": None}
        service = TranscriptionService()
        service._doubao_key = lambda: "fake_access_token"
        
        with patch("pathlib.Path.is_file", return_value=True), patch("pathlib.Path.stat", return_value=type("Stat", (), {"st_size": 1000, "st_mtime": 100.0})()):
            result = await service.transcribe_file("fake_audio.mp3", provider="doubao")
            self.assertEqual(result["text"], "转写结果")
            self.assertEqual(result["provider"], "doubao")

    @patch("services.doubao_asr_provider.websockets.connect")
    async def test_doubao_asr_transcribe_file_connect(self, mock_connect):
        import json
        import struct
        from services.doubao_asr_provider import doubao_asr_transcribe_file
        
        mock_ws = AsyncMock()
        hdr = _build_header(msg_type=9, flags=2, serialization=1, compression=0)
        resp_json = json.dumps({"result": {"text": "测试结果"}, "audio_info": {"duration": 1500}}).encode("utf-8")
        payload_size = struct.pack("!I", len(resp_json))
        server_frame = hdr + payload_size + resp_json
        
        mock_ws.recv.return_value = server_frame
        mock_connect.return_value.__aenter__.return_value = mock_ws
        
        with patch("pathlib.Path.exists", return_value=True), \
             patch("builtins.open", unittest.mock.mock_open(read_data=b"fake_audio")):
            res = await doubao_asr_transcribe_file("dummy.mp3", api_key="test_key")
            
        self.assertEqual(res["text"], "测试结果")
        mock_connect.assert_called_once()
        _, kwargs = mock_connect.call_args
        self.assertIn("additional_headers", kwargs)
        self.assertNotIn("extra_headers", kwargs)
        self.assertEqual(kwargs["additional_headers"]["X-Api-Key"], "test_key")
        self.assertNotIn("Authorization", kwargs["additional_headers"])


if __name__ == "__main__":
    unittest.main()
