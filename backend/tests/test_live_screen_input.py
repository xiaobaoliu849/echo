import base64
from io import BytesIO
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from PIL import Image

from services.live_screen_input import decode_screen_frame, MAX_SCREEN_FRAME_BYTES
from services.realtime_google_provider import GoogleRealtimeMixin
from services.realtime_vercel_provider import VercelRealtimeMixin


def frame(width=768, height=432, format="JPEG"):
    output = BytesIO()
    Image.new("RGB", (width, height), "white").save(output, format=format)
    return {"type": "screen_frame", "mime_type": "image/jpeg", "data": base64.b64encode(output.getvalue()).decode()}


class ScreenFrameValidationTests(unittest.TestCase):
    def test_valid_frame(self):
        self.assertTrue(decode_screen_frame(frame()).startswith(b"\xff\xd8"))

    def test_invalid_or_unbounded_frames(self):
        for payload in [
            frame(width=769), frame(format="PNG"),
            {**frame(), "mime_type": "image/png"},
            {**frame(), "data": "invalid!"},
            {**frame(), "data": "A" * (MAX_SCREEN_FRAME_BYTES * 4 // 3 + 1)},
            {**frame(), "data": ""}, {**frame(), "data": []},
            {**frame(), "data": base64.b64encode(base64.b64decode(frame()["data"])[:-100]).decode()},
        ]:
            with self.subTest(payload_type=type(payload.get("data"))):
                with self.assertRaises(ValueError):
                    decode_screen_frame(payload)


class ScreenFrameTransportTests(unittest.IsolatedAsyncioTestCase):
    def websocket(self, messages):
        return MagicMock(receive=AsyncMock(side_effect=[
            {"type": "websocket.receive", "text": json.dumps(message)} for message in messages
        ] + [{"type": "websocket.receive", "bytes": b"pcm"}, {"type": "websocket.disconnect"}]))

    async def test_google_frame_does_not_touch_transcripts_or_end_audio_turn(self):
        provider = GoogleRealtimeMixin()
        provider._send_event = AsyncMock()
        websocket = self.websocket([frame(), frame(), frame()])
        session = MagicMock(send_realtime_input=AsyncMock())
        memory, recorder = MagicMock(), MagicMock()
        with patch("services.realtime_google_provider.time.monotonic", side_effect=[10, 10.5, 11]):
            await provider._client_to_google_loop(websocket, session, memory, MagicMock(), recorder, model="gemini-3.8-live")
        calls = session.send_realtime_input.call_args_list
        self.assertEqual(len(calls), 3)  # Two frames and continued microphone audio.
        self.assertEqual(calls[0].kwargs["video"].mime_type, "image/jpeg")
        self.assertEqual(calls[-1].kwargs["audio"].data, b"pcm")
        memory.note_user_transcript.assert_not_called()
        recorder.note_user_transcript.assert_not_called()
        session.send.assert_not_called()
        provider._send_event.assert_not_called()

    async def test_translation_and_other_models_reject_frames_but_keep_audio(self):
        for model, translate in [("gemini-3.5-live-translate-preview", True), ("gemini-3.8-live-extended-thinking", False)]:
            provider = GoogleRealtimeMixin()
            provider._send_event = AsyncMock()
            session = MagicMock(send_realtime_input=AsyncMock())
            await provider._client_to_google_loop(self.websocket([frame()]), session, MagicMock(), MagicMock(), is_live_translate=translate, model=model)
            self.assertEqual(session.send_realtime_input.call_count, 1)
            self.assertIn("audio", session.send_realtime_input.call_args.kwargs)
            provider._send_event.assert_awaited_once()

    async def test_immediate_typed_question_includes_latest_frame_and_stop_clears_it(self):
        provider = GoogleRealtimeMixin()
        provider._send_event = AsyncMock()
        session = MagicMock(send_realtime_input=AsyncMock(), send_client_content=AsyncMock(), send=AsyncMock())
        recorder, memory = MagicMock(note_user_transcript=AsyncMock()), MagicMock()
        await provider._client_to_google_loop(self.websocket([
            frame(), {"type": "text_input", "text": "Explain the lesson"},
            {"type": "screen_share_stopped"}, {"type": "text_input", "text": "Another question"},
        ]), session, memory, MagicMock(), recorder, model="gemini-3.8-live")
        session.send_client_content.assert_awaited_once()
        content = session.send_client_content.call_args.kwargs["turns"]
        self.assertEqual(content.parts[0].inline_data.mime_type, "image/jpeg")
        self.assertEqual(content.parts[1].text, "Explain the lesson")
        self.assertTrue(session.send_client_content.call_args.kwargs["turn_complete"])
        session.send.assert_awaited_once_with(input="Another question", end_of_turn=True)
        self.assertEqual([call.args[0] for call in recorder.note_user_transcript.call_args_list], ["Explain the lesson", "Another question"])

    async def test_malformed_frame_reports_error_without_ending_call(self):
        provider = GoogleRealtimeMixin()
        provider._send_event = AsyncMock()
        session = MagicMock(send_realtime_input=AsyncMock())
        await provider._client_to_google_loop(self.websocket([["invalid"], {**frame(), "data": "bad!"}, frame()]), session, MagicMock(), MagicMock(), model="gemini-3.8-live")
        self.assertEqual(provider._send_event.call_count, 2)
        self.assertEqual(session.send_realtime_input.call_count, 2)

    async def test_vercel_explicitly_rejects_visual_input_without_forwarding_it(self):
        provider = VercelRealtimeMixin()
        provider._send_event = AsyncMock()
        upstream = MagicMock(send=AsyncMock())
        await provider._client_to_vercel_loop(self.websocket([frame(), {"type": "media_input", "data": "image", "text": "describe"}]), upstream, MagicMock(), MagicMock(), model="google/gemini-3.8-live")
        self.assertEqual(provider._send_event.call_count, 2)
        events = [json.loads(call.args[0]) for call in upstream.send.call_args_list]
        self.assertEqual([event["type"] for event in events], ["input-audio-append"])
