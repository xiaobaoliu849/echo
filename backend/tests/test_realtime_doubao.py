"""Tests for Doubao / Volcengine Realtime voice provider mixin."""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from services.interruption_classifier import InterruptionDecisionCoordinator
from services.realtime_voice_service import RealtimeVoiceService
from services.realtime_constants import (
    DEFAULT_DOUBAO_REALTIME_ENDPOINT,
    DEFAULT_DOUBAO_REALTIME_MODEL,
    DEFAULT_DOUBAO_REALTIME_VOICE,
)


class CollectingWebSocket:
    """Collects every JSON payload sent to the client."""

    def __init__(self, inbound: list[dict] | None = None) -> None:
        self.events: list[dict] = []
        self.bytes_sent: list[bytes] = []
        self.inbound = list(inbound or [])

    async def send_json(self, payload: dict) -> None:
        self.events.append(dict(payload))

    async def send_bytes(self, payload: bytes) -> None:
        self.bytes_sent.append(payload)

    async def receive(self) -> dict:
        if self.inbound:
            return self.inbound.pop(0)
        return {"type": "websocket.disconnect"}


class FakeDoubaoWs:
    """Fake Doubao-side WebSocket."""

    def __init__(self, events: list[dict] | None = None) -> None:
        self.sent: list[str] = []
        self._events = list(events or [])

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str:
        if self._events:
            ev = self._events.pop(0)
            return json.dumps(ev)
        # Block until cancelled once events run out
        await asyncio.sleep(3600)
        return ""


class TestRealtimeDoubaoProvider(unittest.TestCase):

    def setUp(self) -> None:
        self.service = RealtimeVoiceService()

    def test_resolve_doubao_settings_success(self) -> None:
        fake_config = MagicMock()
        fake_config.get_provider_settings.side_effect = lambda provider, model: {
            "Doubao": {"api_key": "volc-secret-key", "model": "doubao-realtime", "realtime_base_url": ""},
            "Volcengine": {"api_key": "", "model": "", "realtime_base_url": ""},
        }[provider]
        fake_config.get_setting.return_value = ""
        self.service.config = fake_config

        settings = self.service._resolve_doubao_settings("doubao-realtime", "zh_female_vv_jupiter_bigtts")
        self.assertEqual(settings["api_key"], "volc-secret-key")
        self.assertEqual(settings["model"], "doubao-realtime")
        self.assertEqual(settings["voice"], "zh_female_vv_jupiter_bigtts")
        self.assertEqual(settings["dialog_model"], "1.2.1.1")
        self.assertEqual(settings["endpoint"], DEFAULT_DOUBAO_REALTIME_ENDPOINT)

    def test_resolve_doubao_settings_voice_fallback(self) -> None:
        fake_config = MagicMock()
        fake_config.get_provider_settings.return_value = {
            "api_key": "volc-secret-key", "model": "", "realtime_base_url": "",
        }
        fake_config.get_setting.return_value = ""
        self.service.config = fake_config

        settings = self.service._resolve_doubao_settings(None, "not-a-real-voice")
        self.assertEqual(settings["voice"], DEFAULT_DOUBAO_REALTIME_VOICE)

    def test_resolve_doubao_settings_missing_key_raises(self) -> None:
        fake_config = MagicMock()
        fake_config.get_provider_settings.return_value = {"api_key": "", "model": "", "realtime_base_url": ""}
        fake_config.get_setting.return_value = ""
        self.service.config = fake_config

        with self.assertRaises(RuntimeError) as ctx:
            self.service._resolve_doubao_settings(None, None)
        self.assertIn("Doubao / Volcengine API Key 未配置", str(ctx.exception))

    def test_client_to_doubao_text_input(self) -> None:
        async def run_test():
            client_ws = CollectingWebSocket(inbound=[
                {"type": "websocket.receive", "text": json.dumps({"type": "text_input", "text": "你好，豆包"})},
            ])
            doubao_ws = FakeDoubaoWs()
            mem_session = MagicMock()
            tool_session = MagicMock()

            await self.service._client_to_doubao_loop(
                client_ws, doubao_ws, mem_session, tool_session
            )
            self.assertEqual(len(doubao_ws.sent), 2)
            item_create = json.loads(doubao_ws.sent[0])
            resp_create = json.loads(doubao_ws.sent[1])
            self.assertEqual(item_create["type"], "conversation.item.create")
            self.assertEqual(item_create["item"]["content"][0]["text"], "你好，豆包")
            self.assertEqual(resp_create["type"], "response.create")

        asyncio.run(run_test())

    def test_doubao_to_client_audio_stream(self) -> None:
        async def run_test():
            client_ws = CollectingWebSocket()
            doubao_events = [
                {"type": "response.created", "response": {"id": "resp_001"}},
                {"type": "response.audio_transcript.delta", "delta": "你好"},
                {"type": "response.audio.delta", "delta": "QUJD"},  # base64 "ABC"
                {"type": "response.done"},
            ]
            doubao_ws = FakeDoubaoWs(events=doubao_events)
            mem_session = MagicMock()
            tool_session = MagicMock()

            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(
                    client_ws, doubao_ws, mem_session, tool_session
                )
            )
            await asyncio.sleep(0.1)
            loop_task.cancel()

            audio_events = [e for e in client_ws.events if e.get("type") == "assistant_audio"]
            self.assertEqual(len(audio_events), 1)
            self.assertEqual(audio_events[0]["audio"], "QUJD")

            text_events = [e for e in client_ws.events if e.get("type") == "assistant_text"]
            self.assertTrue(len(text_events) >= 1)
            self.assertIn("你好", text_events[-1]["text"])

        asyncio.run(run_test())

    def test_doubao_session_recorder_methods(self) -> None:
        async def run_test():
            fake_repo = MagicMock()
            from services.realtime_session_recorder import VoiceAgentSessionRecorder
            recorder = VoiceAgentSessionRecorder(fake_repo, "session_123")
            await recorder.record_turn_completed()
            await recorder.complete_session()
            self.assertTrue(fake_repo.finish_session.called)

        asyncio.run(run_test())


class FakeOpenSpeechWs:
    """Fake Doubao-side WebSocket speaking the OpenSpeech binary protocol."""

    def __init__(self, frames: list[bytes] | None = None) -> None:
        self.sent: list[bytes] = []
        self._frames = list(frames or [])

    async def send(self, data: bytes) -> None:
        self.sent.append(data)

    async def recv(self) -> bytes:
        if self._frames:
            return self._frames.pop(0)
        await asyncio.sleep(3600)
        return b""


class TestDoubaoOpenSpeechProtocol(unittest.TestCase):
    """End-to-end tests of the OpenSpeech dialogue binary-protocol path."""

    def setUp(self) -> None:
        self.service = RealtimeVoiceService()

    def test_handshake_sends_start_connection_then_start_session(self) -> None:
        async def run_test():
            from services.openspeech_dialogue_protocol import (
                EVENT_CONNECTION_STARTED,
                EVENT_SESSION_STARTED,
                EVENT_START_CONNECTION,
                EVENT_START_SESSION,
                MSG_TYPE_FULL_CLIENT_REQ,
                decode_openspeech_frame,
                encode_openspeech_frame,
            )
            doubao_ws = FakeOpenSpeechWs(frames=[
                encode_openspeech_frame(MSG_TYPE_FULL_CLIENT_REQ, {}, event=EVENT_CONNECTION_STARTED),
                encode_openspeech_frame(MSG_TYPE_FULL_CLIENT_REQ, {"dialog_id": "d1"}, event=EVENT_SESSION_STARTED, session_id="sid-1"),
            ])
            session_id = await self.service._openspeech_handshake(
                doubao_ws, voice="zh_female_vv_jupiter_bigtts",
                instructions=None, dialog_model="1.2.1.1",
            )
            self.assertTrue(session_id)
            self.assertEqual(len(doubao_ws.sent), 2)

            first = decode_openspeech_frame(doubao_ws.sent[0])
            self.assertEqual(first.event, EVENT_START_CONNECTION)
            self.assertEqual(first.payload, b"{}")

            second = decode_openspeech_frame(doubao_ws.sent[1])
            self.assertEqual(second.event, EVENT_START_SESSION)
            self.assertEqual(second.session_id, session_id)
            payload = json.loads(second.payload.decode("utf-8"))
            self.assertEqual(payload["tts"]["speaker"], "zh_female_vv_jupiter_bigtts")
            self.assertEqual(payload["dialog"]["extra"]["model"], "1.2.1.1")
            self.assertEqual(payload["asr"]["audio_info"]["sample_rate"], 16000)
            self.assertIn("extra", payload["asr"])  # 置空会触发 42000020

        asyncio.run(run_test())

    def test_handshake_connection_failed_raises(self) -> None:
        async def run_test():
            from services.openspeech_dialogue_protocol import (
                EVENT_CONNECTION_FAILED,
                MSG_TYPE_FULL_CLIENT_REQ,
                encode_openspeech_frame,
            )
            doubao_ws = FakeOpenSpeechWs(frames=[
                encode_openspeech_frame(MSG_TYPE_FULL_CLIENT_REQ, {"error": "bad app id"}, event=EVENT_CONNECTION_FAILED),
            ])
            with self.assertRaises(RuntimeError) as ctx:
                await self.service._openspeech_handshake(
                    doubao_ws, voice="v", instructions=None, dialog_model="1.2.1.1",
                )
            self.assertIn("bad app id", str(ctx.exception))

        asyncio.run(run_test())

    def test_openspeech_audio_upload_uses_task_request(self) -> None:
        async def run_test():
            from services.openspeech_dialogue_protocol import (
                EVENT_TASK_REQUEST,
                MSG_TYPE_AUDIO_CLIENT_REQ,
                decode_openspeech_frame,
            )
            client_ws = CollectingWebSocket(inbound=[
                {"type": "websocket.receive", "bytes": b"\x01\x02" * 320},
            ])
            doubao_ws = FakeOpenSpeechWs()
            await self.service._client_to_doubao_loop(
                client_ws, doubao_ws, MagicMock(), MagicMock(),
                is_openspeech=True, session_id="sid-9",
            )
            self.assertEqual(len(doubao_ws.sent), 1)
            frame = decode_openspeech_frame(doubao_ws.sent[0])
            self.assertEqual(frame.msg_type, MSG_TYPE_AUDIO_CLIENT_REQ)
            self.assertEqual(frame.event, EVENT_TASK_REQUEST)
            self.assertEqual(frame.session_id, "sid-9")
            self.assertEqual(frame.payload, b"\x01\x02" * 320)

        asyncio.run(run_test())

    def test_openspeech_empty_sentence_text_falls_back_to_chat_response(self) -> None:
        """实测真实流量: 550 增量文本先到,350 的 text 为空 — 文本必须来自 550。"""
        async def run_test():
            from services.openspeech_dialogue_protocol import (
                EVENT_CHAT_ENDED,
                EVENT_CHAT_RESPONSE,
                EVENT_TTS_SENTENCE_START,
                MSG_TYPE_FULL_SERVER_RESP,
                encode_openspeech_frame,
            )
            frames = [
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"content": "我是", "reply_id": "r1"}, event=EVENT_CHAT_RESPONSE, session_id="sid-1"),
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"content": "豆包。", "reply_id": "r1"}, event=EVENT_CHAT_RESPONSE, session_id="sid-1"),
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"text": "", "reply_id": "r1"}, event=EVENT_TTS_SENTENCE_START, session_id="sid-1"),
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"reply_id": "r1"}, event=EVENT_CHAT_ENDED, session_id="sid-1"),
            ]
            client_ws = CollectingWebSocket()
            doubao_ws = FakeOpenSpeechWs(frames=frames)
            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(
                    client_ws, doubao_ws, MagicMock(), MagicMock(),
                    is_openspeech=True, session_id="sid-1",
                )
            )
            await asyncio.sleep(0.1)
            loop_task.cancel()

            ai_final = [e for e in client_ws.events if e["type"] == "ai_transcript"]
            self.assertEqual(len(ai_final), 1)
            self.assertEqual(ai_final[0]["text"], "我是豆包。")
            text_deltas = [e["text"] for e in client_ws.events if e["type"] == "assistant_text"]
            self.assertEqual(text_deltas, ["我是", "豆包。"])

        asyncio.run(run_test())

    def test_openspeech_asr_interim_then_final_no_duplicate(self) -> None:
        """interim 必须带 interim=True(前端原位更新),final 只发一次 —— 重复气泡的回归测试。"""
        async def run_test():
            from services.openspeech_dialogue_protocol import (
                EVENT_ASR_ENDED,
                EVENT_ASR_INFO,
                EVENT_ASR_RESPONSE,
                MSG_TYPE_FULL_SERVER_RESP,
                encode_openspeech_frame,
            )
            frames = [
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"question_id": "q1"}, event=EVENT_ASR_INFO, session_id="sid-1"),
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"results": [{"text": "今天西安的", "is_interim": True}]}, event=EVENT_ASR_RESPONSE, session_id="sid-1"),
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"results": [{"text": "今天西安的天气怎么样", "is_interim": False}]}, event=EVENT_ASR_RESPONSE, session_id="sid-1"),
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {}, event=EVENT_ASR_ENDED, session_id="sid-1"),
            ]
            client_ws = CollectingWebSocket()
            doubao_ws = FakeOpenSpeechWs(frames=frames)
            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(
                    client_ws, doubao_ws, MagicMock(), MagicMock(),
                    is_openspeech=True, session_id="sid-1",
                )
            )
            await asyncio.sleep(0.1)
            loop_task.cancel()

            transcripts = [e for e in client_ws.events if e["type"] == "user_transcript"]
            self.assertEqual(len(transcripts), 2)
            self.assertTrue(transcripts[0].get("interim"))
            self.assertEqual(transcripts[0]["text"], "今天西安的")
            self.assertFalse(transcripts[1].get("interim", False))
            self.assertEqual(transcripts[1]["text"], "今天西安的天气怎么样")

        asyncio.run(run_test())

    def test_openspeech_asr_ended_sends_final_when_only_interim_seen(self) -> None:
        async def run_test():
            from services.openspeech_dialogue_protocol import (
                EVENT_ASR_ENDED,
                EVENT_ASR_RESPONSE,
                MSG_TYPE_FULL_SERVER_RESP,
                encode_openspeech_frame,
            )
            frames = [
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"results": [{"text": "只有中间结果", "is_interim": True}]}, event=EVENT_ASR_RESPONSE, session_id="sid-1"),
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {}, event=EVENT_ASR_ENDED, session_id="sid-1"),
            ]
            client_ws = CollectingWebSocket()
            doubao_ws = FakeOpenSpeechWs(frames=frames)
            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(
                    client_ws, doubao_ws, MagicMock(), MagicMock(),
                    is_openspeech=True, session_id="sid-1",
                )
            )
            await asyncio.sleep(0.1)
            loop_task.cancel()

            transcripts = [e for e in client_ws.events if e["type"] == "user_transcript"]
            finals = [e for e in transcripts if not e.get("interim")]
            self.assertEqual(len(finals), 1)
            self.assertEqual(finals[0]["text"], "只有中间结果")

        asyncio.run(run_test())

    def test_openspeech_server_events_turn_flow(self) -> None:
        async def run_test():
            from services.openspeech_dialogue_protocol import (
                EVENT_ASR_INFO,
                EVENT_TTS_ENDED,
                EVENT_TTS_RESPONSE,
                EVENT_TTS_SENTENCE_START,
                MSG_TYPE_AUDIO_SERVER_RESP,
                MSG_TYPE_FULL_SERVER_RESP,
                encode_openspeech_frame,
            )
            frames = [
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"text": "你好呀", "reply_id": "r1"}, event=EVENT_TTS_SENTENCE_START, session_id="sid-1"),
                encode_openspeech_frame(MSG_TYPE_AUDIO_SERVER_RESP, b"\x00\x01" * 100, event=EVENT_TTS_RESPONSE, session_id="sid-1"),
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {}, event=EVENT_TTS_ENDED, session_id="sid-1"),
                # barge-in while a second turn is playing
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"text": "第二句", "reply_id": "r2"}, event=EVENT_TTS_SENTENCE_START, session_id="sid-1"),
                encode_openspeech_frame(MSG_TYPE_FULL_SERVER_RESP, {"question_id": "q2"}, event=EVENT_ASR_INFO, session_id="sid-1"),
            ]
            client_ws = CollectingWebSocket()
            doubao_ws = FakeOpenSpeechWs(frames=frames)
            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(
                    client_ws, doubao_ws, MagicMock(), MagicMock(),
                    is_openspeech=True, session_id="sid-1",
                )
            )
            await asyncio.sleep(0.1)
            loop_task.cancel()

            types = [e["type"] for e in client_ws.events]
            self.assertIn("assistant_text", types)
            self.assertIn("assistant_audio", types)
            self.assertIn("ai_transcript", types)
            self.assertIn("interrupted", types)

            audio_events = [e for e in client_ws.events if e["type"] == "assistant_audio"]
            self.assertEqual(audio_events[0]["sample_rate"], 24000)
            ai_final = [e for e in client_ws.events if e["type"] == "ai_transcript"]
            self.assertEqual(ai_final[0]["text"], "你好呀")
            interrupted = [e for e in client_ws.events if e["type"] == "interrupted"]
            self.assertEqual(interrupted[0]["turn_id"], "r2")

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
