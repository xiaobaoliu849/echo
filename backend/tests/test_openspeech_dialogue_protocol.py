"""Tests for OpenSpeech Dialogue binary protocol encoder/decoder."""
import json
import unittest

from services.openspeech_dialogue_protocol import (
    MSG_TYPE_AUDIO_CLIENT_REQ,
    MSG_TYPE_FULL_CLIENT_REQ,
    MSG_TYPE_FULL_SERVER_RESP,
    SERIALIZATION_JSON,
    decode_openspeech_frame,
    encode_openspeech_frame,
)


class TestOpenSpeechDialogueProtocol(unittest.TestCase):
    def test_encode_decode_json_frame(self) -> None:
        payload = {"type": "start_session", "session": {"voice": "zh_female_shuangkuailiangli"}}
        encoded = encode_openspeech_frame(
            msg_type=MSG_TYPE_FULL_CLIENT_REQ,
            payload=payload,
            event=100,
            session_id="test_session_123",
        )
        self.assertGreater(len(encoded), 12)

        decoded = decode_openspeech_frame(encoded)
        self.assertEqual(decoded.msg_type, MSG_TYPE_FULL_CLIENT_REQ)
        self.assertEqual(decoded.serialization, SERIALIZATION_JSON)
        self.assertEqual(decoded.event, 100)
        self.assertEqual(decoded.payload.decode("utf-8"), '{"type": "start_session", "session": {"voice": "zh_female_shuangkuailiangli"}}')

    def test_encode_decode_raw_audio_frame(self) -> None:
        pcm_data = b"\x00\x01\x02\x03\x04\x05" * 100
        encoded = encode_openspeech_frame(
            msg_type=MSG_TYPE_AUDIO_CLIENT_REQ,
            payload=pcm_data,
        )
        decoded = decode_openspeech_frame(encoded)
        self.assertEqual(decoded.msg_type, MSG_TYPE_AUDIO_CLIENT_REQ)
        self.assertEqual(decoded.payload, pcm_data)

    def test_start_connection_matches_official_byte_example(self) -> None:
        """官方文档示例: StartConnection = [17 20 16 0 0 0 0 1 0 0 0 2 123 125]."""
        from services.openspeech_dialogue_protocol import EVENT_START_CONNECTION
        encoded = encode_openspeech_frame(
            msg_type=MSG_TYPE_FULL_CLIENT_REQ,
            payload={},
            event=EVENT_START_CONNECTION,
        )
        self.assertEqual(
            list(encoded),
            [17, 20, 16, 0, 0, 0, 0, 1, 0, 0, 0, 2, 123, 125],
        )

    def test_session_event_frame_matches_official_byte_example(self) -> None:
        """官方文档 StartSession 字节示例 (无 sequence、session id 跟随 event 字段)。"""
        from services.openspeech_dialogue_protocol import EVENT_START_SESSION
        session_id = "75a6126e-427f-49a1-a2c1-621143cb9db3"
        payload = {"dialog": {"bot_name": "豆包", "dialog_id": "", "extra": None}}
        encoded = encode_openspeech_frame(
            msg_type=MSG_TYPE_FULL_CLIENT_REQ,
            payload=payload,
            event=EVENT_START_SESSION,
            session_id=session_id,
        )
        decoded = decode_openspeech_frame(encoded)
        self.assertEqual(decoded.event, EVENT_START_SESSION)
        self.assertEqual(decoded.session_id, session_id)
        self.assertEqual(decoded.sequence, None)
        restored = json.loads(decoded.payload.decode("utf-8"))
        self.assertEqual(restored["dialog"]["bot_name"], "豆包")

    def test_server_audio_frame_with_session_id(self) -> None:
        """TTSResponse 音频帧: event=352 + session id + 二进制 payload。"""
        from services.openspeech_dialogue_protocol import (
            EVENT_TTS_RESPONSE,
            MSG_TYPE_AUDIO_SERVER_RESP,
        )
        audio = b"\x4f\x67\x67\x53" * 10
        encoded = encode_openspeech_frame(
            msg_type=MSG_TYPE_AUDIO_SERVER_RESP,
            payload=audio,
            event=EVENT_TTS_RESPONSE,
            session_id="3c791a7d-227a-4446-993b-24f9e302cc98",
        )
        decoded = decode_openspeech_frame(encoded)
        self.assertEqual(decoded.msg_type, MSG_TYPE_AUDIO_SERVER_RESP)
        self.assertEqual(decoded.event, EVENT_TTS_RESPONSE)
        self.assertEqual(decoded.session_id, "3c791a7d-227a-4446-993b-24f9e302cc98")
        self.assertEqual(decoded.payload, audio)

    def test_error_frame_carries_code(self) -> None:
        from services.openspeech_dialogue_protocol import MSG_TYPE_ERROR_INFO
        encoded = encode_openspeech_frame(
            msg_type=MSG_TYPE_ERROR_INFO,
            payload={"error": "boom"},
            event=599,
        )
        # error frames carry a 4-byte code; emulate the server by injecting it
        with_code = encoded[:4] + (45000003).to_bytes(4, "big") + encoded[4:]
        decoded = decode_openspeech_frame(with_code)
        self.assertEqual(decoded.msg_type, MSG_TYPE_ERROR_INFO)
        self.assertEqual(decoded.code, 45000003)
        self.assertEqual(decoded.event, 599)


if __name__ == "__main__":
    unittest.main()
