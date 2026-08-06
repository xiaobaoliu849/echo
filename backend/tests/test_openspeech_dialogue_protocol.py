"""Tests for OpenSpeech Dialogue binary protocol encoder/decoder."""
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


if __name__ == "__main__":
    unittest.main()
