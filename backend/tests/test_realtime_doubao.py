"""Tests for Doubao / Volcengine Realtime voice provider mixin.

Doubao realtime speaks only the 全双工 (duplex) JSON protocol since the legacy
OpenSpeech binary path was removed on 2026-08-24.
"""

import asyncio
import base64
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

from services.interruption_classifier import InterruptionDecisionCoordinator
from services.realtime_voice_service import RealtimeVoiceService
from services.realtime_constants import (
    DEFAULT_DOUBAO_DUPLEX_DIALOG_MODEL,
    DEFAULT_DOUBAO_DUPLEX_ENDPOINT,
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
    """Fake Doubao-side WebSocket speaking the duplex JSON protocol."""

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


def _default_config(
    api_key: str = "uuid-style-api-key",
    access_token: str | None = None,
) -> MagicMock:
    """Fake BackendConfig. ``api_key`` feeds provider_settings (Ark chat key);
    realtime voice reads only doubao_access_token, which defaults to the same
    value for fixture convenience."""
    fake_config = MagicMock()
    fake_config.get_provider_settings.return_value = {
        "api_key": api_key, "model": "", "realtime_base_url": "",
    }
    token = access_token if access_token is not None else api_key
    fake_config.get_setting.side_effect = lambda key, default="": {
        "doubao_access_token": token,
    }.get(key, default)
    return fake_config


class TestRealtimeDoubaoSettings(unittest.TestCase):
    """Credential resolution — single duplex transport."""

    def setUp(self) -> None:
        self.service = RealtimeVoiceService()

    def test_resolve_defaults_to_duplex(self) -> None:
        fake_config = _default_config()
        fake_config.get_provider_settings.return_value = {
            "api_key": "uuid-style-api-key", "model": "doubao-realtime", "realtime_base_url": "",
        }
        self.service.config = fake_config

        settings = self.service._resolve_doubao_settings("doubao-realtime", "zh_female_vv_jupiter_bigtts")
        self.assertEqual(settings["api_key"], "uuid-style-api-key")
        self.assertEqual(settings["endpoint"], DEFAULT_DOUBAO_DUPLEX_ENDPOINT)
        self.assertEqual(settings["dialog_model"], DEFAULT_DOUBAO_DUPLEX_DIALOG_MODEL)
        self.assertEqual(settings["voice"], "zh_female_vv_jupiter_bigtts")
        # 旧协议相关字段已彻底移除
        self.assertNotIn("mode", settings)
        self.assertNotIn("app_id", settings)

    def test_resolve_custom_endpoint_passthrough(self) -> None:
        """自定义 realtime_base_url 直接透传(仍说全双工协议)。"""
        fake_config = _default_config()
        fake_config.get_provider_settings.return_value = {
            "api_key": "k", "model": "",
            "realtime_base_url": "wss://example.internal/duplex/realtime/dialogue",
        }
        self.service.config = fake_config

        settings = self.service._resolve_doubao_settings(None, None)
        self.assertEqual(settings["endpoint"], "wss://example.internal/duplex/realtime/dialogue")

    def test_resolve_access_token_preferred(self) -> None:
        """实时语音只认独立的 doubao_access_token 字段。"""
        fake_config = _default_config(api_key="ark-style-key")
        fake_config.get_setting.side_effect = lambda key, default="": {
            "doubao_access_token": "new-console-api-key",
        }.get(key, default)
        self.service.config = fake_config

        settings = self.service._resolve_doubao_settings(None, None)
        self.assertEqual(settings["api_key"], "new-console-api-key")

    def test_resolve_voice_fallback(self) -> None:
        self.service.config = _default_config()
        settings = self.service._resolve_doubao_settings(None, "not-a-real-voice")
        self.assertEqual(settings["voice"], DEFAULT_DOUBAO_REALTIME_VOICE)

    def test_resolve_missing_credential_raises(self) -> None:
        """凭证缺失即报错;doubao_api_key(方舟文字聊天钥匙)不再回退用作语音凭证。"""
        self.service.config = _default_config(api_key="ark-style-key", access_token="")
        with self.assertRaises(RuntimeError) as ctx:
            self.service._resolve_doubao_settings(None, None)
        self.assertIn("凭证未配置", str(ctx.exception))


class TestDoubaoDuplexHandshake(unittest.TestCase):

    def setUp(self) -> None:
        self.service = RealtimeVoiceService()

    def test_handshake_sends_session_create(self) -> None:
        async def run_test():
            doubao_ws = FakeDoubaoWs(events=[
                {"type": "session.created", "session": {"id": "dlg-1"}},
            ])
            dialog_id = await self.service._duplex_handshake(
                doubao_ws, voice="zh_female_vv_jupiter_bigtts",
                instructions="你是助手", dialog_model=DEFAULT_DOUBAO_DUPLEX_DIALOG_MODEL,
            )
            self.assertEqual(dialog_id, "dlg-1")
            self.assertEqual(len(doubao_ws.sent), 1)
            evt = json.loads(doubao_ws.sent[0])
            self.assertEqual(evt["type"], "session.create")
            self.assertEqual(evt["session"]["model"], DEFAULT_DOUBAO_DUPLEX_DIALOG_MODEL)
            self.assertEqual(evt["session"]["instructions"], "你是助手")
            self.assertEqual(evt["session"]["audio"]["output"]["voice"], "zh_female_vv_jupiter_bigtts")
            self.assertEqual(evt["session"]["audio"]["input"]["format"]["rate"], 16000)
            self.assertEqual(evt["session"]["audio"]["output"]["format"]["type"], "pcm_s16le")
            self.assertIn("extension", evt)

        asyncio.run(run_test())

    def test_handshake_includes_websearch_extension(self) -> None:
        async def run_test():
            doubao_ws = FakeDoubaoWs(events=[
                {"type": "session.created", "session": {"id": "dlg-1"}},
            ])
            await self.service._duplex_handshake(
                doubao_ws, voice="v", instructions=None,
                dialog_model=DEFAULT_DOUBAO_DUPLEX_DIALOG_MODEL,
                websearch_key="ws-key",
            )
            evt = json.loads(doubao_ws.sent[0])
            extra = evt["extension"]["dialog"]["extra"]
            self.assertTrue(extra["enable_volc_websearch"])
            self.assertEqual(extra["volc_websearch_api_key"], "ws-key")

        asyncio.run(run_test())

    def test_handshake_error_raises(self) -> None:
        async def run_test():
            doubao_ws = FakeDoubaoWs(events=[
                {"type": "error", "error": {"message": "invalid api key", "status_code": 401}},
            ])
            with self.assertRaises(RuntimeError) as ctx:
                await self.service._duplex_handshake(
                    doubao_ws, voice="v", instructions=None,
                    dialog_model=DEFAULT_DOUBAO_DUPLEX_DIALOG_MODEL,
                )
            self.assertIn("invalid api key", str(ctx.exception))

        asyncio.run(run_test())


class TestDoubaoDuplexClientLoop(unittest.TestCase):

    def setUp(self) -> None:
        self.service = RealtimeVoiceService()

    def test_audio_upload_uses_json_append(self) -> None:
        async def run_test():
            client_ws = CollectingWebSocket(inbound=[
                {"type": "websocket.receive", "bytes": b"\x01\x02" * 320},
            ])
            doubao_ws = FakeDoubaoWs()
            await self.service._client_to_doubao_loop(
                client_ws, doubao_ws, MagicMock(), MagicMock(),
            )
            self.assertEqual(len(doubao_ws.sent), 1)
            evt = json.loads(doubao_ws.sent[0])
            self.assertEqual(evt["type"], "input_audio_buffer.append")
            self.assertEqual(base64.b64decode(evt["audio"]), b"\x01\x02" * 320)

        asyncio.run(run_test())

    def test_text_input_creates_context_item_with_notice(self) -> None:
        """全双工没有文本触发回复的事件:只进上下文并发非致命提示,不发 response.create。"""
        async def run_test():
            client_ws = CollectingWebSocket(inbound=[
                {"type": "websocket.receive", "text": json.dumps({"type": "text_input", "text": "你好"})},
            ])
            doubao_ws = FakeDoubaoWs()
            mem_session = MagicMock()
            await self.service._client_to_doubao_loop(
                client_ws, doubao_ws, mem_session, MagicMock(),
            )
            mem_session.note_user_transcript.assert_called_with("你好")
            self.assertEqual(len(doubao_ws.sent), 1)
            evt = json.loads(doubao_ws.sent[0])
            self.assertEqual(evt["type"], "conversation.item.create")
            item = evt["items"][0]
            self.assertEqual(item["role"], "user")
            self.assertEqual(item["content"][0]["text"], "你好")
            self.assertNotIn("response.create", doubao_ws.sent[0])
            # 非致命提示(error 事件会终止会话,不能用)
            notices = [e for e in client_ws.events if e["type"] == "agent_progress"]
            self.assertEqual(len(notices), 1)
            self.assertEqual(notices[0]["stage"], "text_context_only")

        asyncio.run(run_test())


class TestDoubaoDuplexTranscriptSemantics(unittest.TestCase):
    """2026-08-24 实机抓包确认的两条协议语义的回归防线。

    1. input_audio_transcription.delta 是"截至目前"的完整快照(且会回退修订),
       必须整体替换 —— 按增量累加会让 interim 文本重复刷屏。
    2. response.output_text.delta 常先于同轮 output_audio.started 到达,
       不得被任何按轮次开启的抑制窗吞掉。
    """

    def setUp(self) -> None:
        self.service = RealtimeVoiceService()

    def test_missing_suffix_helper(self) -> None:
        f = self.service._duplex_missing_text_suffix
        self.assertEqual(f("", "abc"), "abc")          # 无增量 → 全文兜底
        self.assertEqual(f("ab", "abcd"), "cd")        # 前缀延伸 → 补后缀
        self.assertEqual(f("abc", "abc"), "")          # 一致 → 不补发
        self.assertEqual(f("abc", ""), "")             # 空全文 → 无操作
        self.assertEqual(f("abc", "xbc"), "")          # 分歧 → 不安全拼接

    def test_suppression_helper(self) -> None:
        f = self.service._duplex_output_suppressed
        self.assertFalse(f({"suppressed_response_id": None}, "r1"))
        self.assertTrue(f({"suppressed_response_id": "r1"}, "r1"))   # 精确命中
        self.assertTrue(f({"suppressed_response_id": "r1"}, ""))     # 缺 id 保守丢弃
        self.assertFalse(f({"suppressed_response_id": "r1"}, "r2"))  # 新一轮不受影响
        self.assertTrue(f({"suppressed_response_id": ""}, "r9"))     # 未知id → 窗口内全抑制

    def test_asr_delta_interim_is_snapshot_not_accumulation(self) -> None:
        async def run_test():
            snapshots = ["你", "你是谁", "你是谁呀？你叫什么名字？", "你是谁呀你叫什么名字"]
            events = [
                {"type": "conversation.item.input_audio_transcription.delta", "delta": s}
                for s in snapshots
            ] + [{"type": "session.closed"}]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(client_ws, doubao_ws, MagicMock(), MagicMock())
            )
            await asyncio.sleep(0.15)
            loop_task.cancel()

            interims = [e["text"] for e in client_ws.events
                        if e["type"] == "user_transcript" and e.get("interim")]
            # 每条 interim 都等于快照原文(含回缩修订),绝不能出现累加重复
            self.assertEqual(interims, snapshots)

        asyncio.run(run_test())

    def test_reply_text_before_audio_started_is_forwarded(self) -> None:
        """真实顺序:文本增量先于本轮 audio.started 到达,必须全部转发。

        回归背景:旧实现在用户开口时开一刀切抑制窗、直到下一轮
        output_audio.started 才解除,导致每轮回复的开头文本被整段吞掉。
        """
        async def run_test():
            fake_mem_session = MagicMock()
            fake_mem_session.flush_turn = AsyncMock(return_value={
                "attempted_count": 0, "saved_count": 0, "failed_count": 0,
            })
            events = [
                # 用户说话(真实流量中 transcription.started 必然先到)
                {"type": "conversation.item.input_audio_transcription.started"},
                {"type": "conversation.item.input_audio_transcription.completed",
                 "transcript": "你是谁"},
                # 文本增量先于音频开始(实测头部 6 字都在这个窗口里)
                {"type": "response.output_text.delta", "delta": "我是豆包，是", "response_id": "r1"},
                {"type": "response.output_audio.started", "response_id": "r1"},
                {"type": "response.output_text.delta", "delta": "能陪你聊天的AI。", "response_id": "r1"},
                {"type": "response.output_text.done",
                 "text": "我是豆包，是能陪你聊天的AI。", "response_id": "r1"},
                {"type": "response.output_audio.done", "response_id": "r1"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(
                    client_ws, doubao_ws, fake_mem_session, MagicMock(),
                )
            )
            await asyncio.sleep(0.15)
            loop_task.cancel()

            texts = "".join(e["text"] for e in client_ws.events if e["type"] == "assistant_text")
            self.assertEqual(texts, "我是豆包，是能陪你聊天的AI。")
            turn_completes = [e for e in client_ws.events if e["type"] == "turn_complete"]
            self.assertEqual(len(turn_completes), 1)

        asyncio.run(run_test())

    def test_multi_segment_reply_keeps_accumulation_baseline(self) -> None:
        """服务端把一条逻辑回复拆成多个 response_id 分段(实测):
        换段不得清空已累积文本,否则 done 对账基线断裂、误报分歧。
        """
        async def run_test():
            events = [
                {"type": "conversation.item.input_audio_transcription.started"},
                {"type": "conversation.item.input_audio_transcription.completed",
                 "transcript": "你是谁"},
                {"type": "response.output_text.delta", "delta": "我是豆包，是", "response_id": "r_a"},
                {"type": "response.output_audio.started", "response_id": "r_a"},
                # 分段切换:同一逻辑回复的下半段换了 response_id
                {"type": "response.output_audio.started", "response_id": "r_b"},
                {"type": "response.output_text.delta", "delta": "，能陪你聊天。", "response_id": "r_b"},
                {"type": "response.output_text.done",
                 "text": "我是豆包，是，能陪你聊天。", "response_id": "r_b"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(client_ws, doubao_ws, MagicMock(), MagicMock())
            )
            await asyncio.sleep(0.15)
            loop_task.cancel()

            texts = [e["text"] for e in client_ws.events if e["type"] == "assistant_text"]
            # done 与累计一致 → 不补发、不重复
            self.assertEqual(texts, ["我是豆包，是", "，能陪你聊天。"])

        asyncio.run(run_test())

    def test_done_text_reconciles_missing_suffix(self) -> None:
        """done.text 与已转发增量对账:缺多少补多少,不重复推送。"""
        async def run_test():
            events = [
                {"type": "response.output_text.delta", "delta": "今天天气", "response_id": "r1"},
                # 模拟异常路径丢了中间增量
                {"type": "response.output_text.done",
                 "text": "今天天气很好，适合出门。", "response_id": "r1"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(client_ws, doubao_ws, MagicMock(), MagicMock())
            )
            await asyncio.sleep(0.15)
            loop_task.cancel()

            texts = [e["text"] for e in client_ws.events if e["type"] == "assistant_text"]
            self.assertEqual(texts, ["今天天气", "很好，适合出门。"])

        asyncio.run(run_test())

    def test_done_text_equal_to_stream_emits_nothing_extra(self) -> None:
        async def run_test():
            events = [
                {"type": "response.output_text.delta", "delta": "完整回复", "response_id": "r1"},
                {"type": "response.output_text.done", "text": "完整回复", "response_id": "r1"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(client_ws, doubao_ws, MagicMock(), MagicMock())
            )
            await asyncio.sleep(0.15)
            loop_task.cancel()

            texts = [e["text"] for e in client_ws.events if e["type"] == "assistant_text"]
            self.assertEqual(texts, ["完整回复"])

        asyncio.run(run_test())


class TestDoubaoDuplexServerLoop(unittest.TestCase):

    def setUp(self) -> None:
        self.service = RealtimeVoiceService()

    def _run_loop(self, doubao_ws: FakeDoubaoWs, client_ws: CollectingWebSocket,
                  recorder=None, memory_session=None):
        loop_task = asyncio.create_task(
            self.service._doubao_to_client_loop(
                client_ws, doubao_ws,
                memory_session if memory_session is not None else MagicMock(),
                MagicMock(), recorder=recorder,
            )
        )
        return loop_task

    async def _drain(self, loop_task) -> None:
        await asyncio.sleep(0.15)
        try:
            await asyncio.wait_for(loop_task, timeout=2)
        except asyncio.TimeoutError:
            loop_task.cancel()

    def test_server_events_turn_flow_with_barge_in(self) -> None:
        async def run_test():
            events = [
                {"type": "conversation.item.input_audio_transcription.delta", "delta": "今天"},
                {"type": "conversation.item.input_audio_transcription.completed",
                 "transcript": "今天天气怎么样"},
                {"type": "response.output_text.delta", "delta": "今天晴", "response_id": "resp_1"},
                {"type": "response.output_audio.started", "response_id": "resp_1", "tts_type": "default"},
                {"type": "response.output_audio.delta", "delta": "QUJD"},  # base64 "ABC"
                # 用户插话 → barge-in
                {"type": "conversation.item.input_audio_transcription.started"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            await self._drain(self._run_loop(doubao_ws, client_ws))

            types = [e["type"] for e in client_ws.events]
            self.assertIn("user_transcript", types)
            self.assertIn("assistant_text", types)
            self.assertIn("assistant_audio", types)
            self.assertIn("interrupted", types)

            transcripts = [e for e in client_ws.events if e["type"] == "user_transcript"]
            self.assertTrue(transcripts[0].get("interim"))
            self.assertEqual(transcripts[0]["text"], "今天")
            finals = [e for e in transcripts if not e.get("interim")]
            self.assertEqual(len(finals), 1)
            self.assertEqual(finals[0]["text"], "今天天气怎么样")

            audio_events = [e for e in client_ws.events if e["type"] == "assistant_audio"]
            self.assertEqual(audio_events[0]["sample_rate"], 24000)
            self.assertEqual(audio_events[0]["encoding"], "pcm_s16le")

            text_deltas = [e["text"] for e in client_ws.events if e["type"] == "assistant_text"]
            self.assertEqual(text_deltas, ["今天晴"])

            # 空 turn_id 让前端无条件停止播报(绕过 turn_id 匹配守卫)
            interrupted = [e for e in client_ws.events if e["type"] == "interrupted"]
            self.assertEqual(interrupted[0]["turn_id"], "")

        asyncio.run(run_test())

    def test_stale_deltas_after_barge_in_are_suppressed(self) -> None:
        """被打断那轮的残余增量必须丢弃;其 done 不触发收尾(不产生空 turn_complete)。"""
        async def run_test():
            fake_recorder = MagicMock()
            fake_recorder.note_user_transcript = AsyncMock(return_value="voice-turn-1")
            fake_recorder.note_assistant_text = AsyncMock(return_value="voice-turn-1")
            fake_recorder.note_assistant_audio = AsyncMock(return_value=("voice-turn-1", 120))
            fake_recorder.interrupt_current_turn = AsyncMock()
            fake_recorder.complete_turn = AsyncMock(return_value="voice-turn-1")

            events = [
                {"type": "conversation.item.input_audio_transcription.completed",
                 "transcript": "第一个问题"},
                {"type": "response.output_text.delta", "delta": "第一句", "response_id": "r1"},
                {"type": "response.output_audio.started", "response_id": "r1"},
                {"type": "response.output_audio.delta", "delta": "QUJD"},
                # 用户插话 → barge-in
                {"type": "conversation.item.input_audio_transcription.started"},
                # 被打断那轮(r1)的残余流:必须全部丢弃
                {"type": "response.output_audio.delta", "delta": "REVG"},
                {"type": "response.output_text.delta", "delta": "残余文本", "response_id": "r1"},
                # r1 迟到的合成结束信号:不得触发收尾
                {"type": "response.output_audio.done", "response_id": "r1"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            await self._drain(self._run_loop(doubao_ws, client_ws, recorder=fake_recorder))

            audio_events = [e for e in client_ws.events if e["type"] == "assistant_audio"]
            self.assertEqual(len(audio_events), 1)  # 只有打断前的 QUJD
            self.assertEqual(audio_events[0]["audio"], "QUJD")
            text_deltas = [e["text"] for e in client_ws.events if e["type"] == "assistant_text"]
            self.assertEqual(text_deltas, ["第一句"])  # 残余文本未转发
            self.assertIn("interrupted", [e["type"] for e in client_ws.events])
            # 打断后的 done 不收尾 → 无 turn_complete、recorder 未 complete_turn
            self.assertNotIn("turn_complete", [e["type"] for e in client_ws.events])
            fake_recorder.complete_turn.assert_not_awaited()

        asyncio.run(run_test())

    def test_done_without_any_output_does_not_finalize(self) -> None:
        """无回复输出的轮次(如 ASR-only/空轮)不做收尾,避免空 turn_complete。"""
        async def run_test():
            fake_recorder = MagicMock()
            fake_recorder.note_user_transcript = AsyncMock(return_value="voice-turn-1")
            fake_recorder.complete_turn = AsyncMock(return_value="")

            events = [
                {"type": "conversation.item.input_audio_transcription.completed",
                 "transcript": "只有识别没有回复"},
                {"type": "response.output_audio.done", "response_id": "r_none"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            await self._drain(self._run_loop(doubao_ws, client_ws, recorder=fake_recorder))

            self.assertNotIn("turn_complete", [e["type"] for e in client_ws.events])
            fake_recorder.complete_turn.assert_not_awaited()

        asyncio.run(run_test())

    def test_new_turn_after_barge_in_resumes_output_and_finalizes(self) -> None:
        """打断后新一轮 started 解除抑制,正常转发并收尾。"""
        async def run_test():
            fake_mem_session = MagicMock()
            fake_mem_session.flush_turn = AsyncMock(return_value={"attempted_count": 0, "saved_count": 0, "failed_count": 0})
            events = [
                {"type": "response.output_audio.started", "response_id": "r1"},
                {"type": "response.output_audio.delta", "delta": "QUJD"},
                {"type": "conversation.item.input_audio_transcription.started"},  # barge-in
                {"type": "response.output_audio.done", "response_id": "r1"},      # r1 残余 done
                # 新一轮
                {"type": "conversation.item.input_audio_transcription.completed", "transcript": "新问题"},
                {"type": "response.output_text.delta", "delta": "新回答", "response_id": "r2"},
                {"type": "response.output_audio.started", "response_id": "r2"},
                {"type": "response.output_audio.delta", "delta": "R0Y="},  # base64 "OT="
                {"type": "response.output_audio.done", "response_id": "r2"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            await self._drain(self._run_loop(doubao_ws, client_ws, memory_session=fake_mem_session))

            audio_events = [e for e in client_ws.events if e["type"] == "assistant_audio"]
            self.assertEqual([a["audio"] for a in audio_events], ["QUJD", "R0Y="])
            self.assertIn("interrupted", [e["type"] for e in client_ws.events])
            # 只有 r2 正常收尾一次
            turn_completes = [e for e in client_ws.events if e["type"] == "turn_complete"]
            self.assertEqual(len(turn_completes), 1)

        asyncio.run(run_test())

    def test_output_audio_done_finalizes_turn_once(self) -> None:
        """output_audio.done 收尾一轮(发 turn_complete);response.done 不重复收尾。"""
        async def run_test():
            fake_recorder = MagicMock()
            fake_recorder.note_user_transcript = AsyncMock(return_value="voice-turn-1")
            fake_recorder.note_assistant_text = AsyncMock(return_value="voice-turn-1")
            fake_recorder.note_assistant_audio = AsyncMock(return_value=("voice-turn-1", 120))
            fake_recorder.complete_turn = AsyncMock(return_value="voice-turn-1")

            fake_mem_session = MagicMock()
            fake_mem_session.flush_turn = AsyncMock(return_value={"attempted_count": 0, "saved_count": 0, "failed_count": 0})

            events = [
                {"type": "conversation.item.input_audio_transcription.completed",
                 "transcript": "唱一段"},
                {"type": "response.output_text.delta", "delta": "抱歉，我不会唱歌", "response_id": "r1"},
                {"type": "response.output_audio.started", "response_id": "r1"},
                {"type": "response.output_audio.done", "response_id": "r1"},
                {"type": "response.done", "response_id": "r1"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            await self._drain(self._run_loop(doubao_ws, client_ws,
                                             recorder=fake_recorder,
                                             memory_session=fake_mem_session))

            types = [e["type"] for e in client_ws.events]
            self.assertIn("turn_complete", types)
            turn_completes = [e for e in client_ws.events if e["type"] == "turn_complete"]
            self.assertEqual(len(turn_completes), 1)
            user_transcripts = [e for e in client_ws.events if e["type"] == "user_transcript"]
            self.assertEqual(user_transcripts[0]["text"], "唱一段")
            self.assertFalse(user_transcripts[0].get("interim", False))
            fake_recorder.complete_turn.assert_awaited()

        asyncio.run(run_test())

    def test_network_tts_type_notifies_websearch_once(self) -> None:
        async def run_test():
            events = [
                {"type": "response.output_audio.started", "response_id": "r1", "tts_type": "network"},
                {"type": "response.output_audio.delta", "delta": "QUJD"},
                {"type": "response.output_audio.delta", "delta": "REVG"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            await self._drain(self._run_loop(doubao_ws, client_ws))

            progress = [e for e in client_ws.events if e["type"] == "agent_progress"]
            self.assertEqual(len(progress), 1)
            self.assertEqual(progress[0]["stage"], "builtin_websearch")

        asyncio.run(run_test())

    def test_error_event_forwarded_and_session_continues(self) -> None:
        async def run_test():
            events = [
                {"type": "error", "error": {"message": "non fatal", "status_code": 52000042}},
                {"type": "response.output_audio.delta", "delta": "QUJD"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            await self._drain(self._run_loop(doubao_ws, client_ws))

            errs = [e for e in client_ws.events if e["type"] == "error"]
            self.assertEqual(len(errs), 1)
            self.assertIn("non fatal", errs[0]["message"])
            # error 之后会话仍在继续(音频照常转发)
            audio_events = [e for e in client_ws.events if e["type"] == "assistant_audio"]
            self.assertEqual(len(audio_events), 1)

        asyncio.run(run_test())

    def test_interruption_coordinator_receives_response_id(self) -> None:
        async def run_test():
            interruption = InterruptionDecisionCoordinator()
            events = [
                {"type": "response.output_audio.started", "response_id": "resp_x"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            loop_task = asyncio.create_task(
                self.service._doubao_to_client_loop(
                    client_ws, doubao_ws, MagicMock(), MagicMock(),
                    interruption=interruption,
                )
            )
            await self._drain(loop_task)
            self.assertEqual(interruption.active_response_id, "resp_x")

        asyncio.run(run_test())


    def test_late_asr_completed_does_not_break_suppression_anchor(self) -> None:
        """对抗审查 P1 回归:迟到的 ASR completed 会把 active_turn_id 覆写成
        recorder 命名空间 id;打断抑制必须仍锚定豆包在播 response_id,
        否则残余流漏抑制(幽灵续播 + 幽灵 turn_complete)。
        """
        async def run_test():
            fake_recorder = MagicMock()
            fake_recorder.note_user_transcript = AsyncMock(return_value="voice-turn-9")
            fake_recorder.note_assistant_text = AsyncMock(return_value="voice-turn-9")
            fake_recorder.note_assistant_audio = AsyncMock(return_value=("voice-turn-9", 120))
            fake_recorder.interrupt_current_turn = AsyncMock()
            fake_recorder.complete_turn = AsyncMock(return_value="voice-turn-9")

            events = [
                {"type": "response.output_audio.started", "response_id": "r1"},
                {"type": "response.output_audio.delta", "delta": "QUJD"},
                # 迟到的 ASR 终稿:把 active_turn_id 覆写为 recorder 命名空间
                {"type": "conversation.item.input_audio_transcription.completed",
                 "transcript": "迟到的识别终稿"},
                # 用户插话 → barge-in:抑制窗必须锚定 "r1" 而非 "voice-turn-9"
                {"type": "conversation.item.input_audio_transcription.started"},
                {"type": "response.output_audio.delta", "delta": "REVG"},
                {"type": "response.output_text.delta", "delta": "残余文本", "response_id": "r1"},
                {"type": "response.output_audio.done", "response_id": "r1"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            await self._drain(self._run_loop(doubao_ws, client_ws, recorder=fake_recorder))

            audio_events = [e for e in client_ws.events if e["type"] == "assistant_audio"]
            self.assertEqual([a["audio"] for a in audio_events], ["QUJD"])  # 残余 REVG 被吞
            texts = [e["text"] for e in client_ws.events if e["type"] == "assistant_text"]
            self.assertEqual(texts, [])  # 残余文本被吞
            self.assertIn("interrupted", [e["type"] for e in client_ws.events])
            self.assertNotIn("turn_complete", [e["type"] for e in client_ws.events])
            fake_recorder.complete_turn.assert_not_awaited()

        asyncio.run(run_test())

    def test_new_reply_text_flows_during_prior_suppression_window(self) -> None:
        """修复核心组合端到端:r1 被打断进入抑制窗后,r2 的文本增量先于 r2 的
        audio.started 到达时必须照常转发(旧一刀切实现正是在这里吞掉回复开头)。
        """
        async def run_test():
            fake_mem_session = MagicMock()
            fake_mem_session.flush_turn = AsyncMock(return_value={
                "attempted_count": 0, "saved_count": 0, "failed_count": 0,
            })
            events = [
                {"type": "response.output_audio.started", "response_id": "r1"},
                {"type": "response.output_audio.delta", "delta": "QUJD"},
                {"type": "conversation.item.input_audio_transcription.started"},  # barge-in
                {"type": "conversation.item.input_audio_transcription.completed",
                 "transcript": "新问题"},
                {"type": "response.output_text.delta", "delta": "新回答开头", "response_id": "r2"},
                {"type": "response.output_audio.started", "response_id": "r2"},   # 此刻才解除抑制
                {"type": "response.output_text.delta", "delta": "后半段", "response_id": "r2"},
                {"type": "response.output_text.done", "text": "新回答开头后半段", "response_id": "r2"},
                {"type": "response.output_audio.done", "response_id": "r2"},
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            await self._drain(self._run_loop(doubao_ws, client_ws, memory_session=fake_mem_session))

            texts = [e["text"] for e in client_ws.events if e["type"] == "assistant_text"]
            self.assertEqual(texts, ["新回答开头", "后半段"])
            self.assertNotIn("新回答开头后半段", texts)  # 对账无缺口 → 不补发
            turn_completes = [e for e in client_ws.events if e["type"] == "turn_complete"]
            self.assertEqual(len(turn_completes), 1)

        asyncio.run(run_test())

    def test_late_text_done_after_finalize_not_repushed(self) -> None:
        """对抗审查 P2 回归:audio.done 已收尾(ai_acc 清空)后迟到的 output_text.done
        不得借"空前缀恒真"把全文再推一遍。
        """
        async def run_test():
            events = [
                {"type": "response.output_text.delta", "delta": "正文", "response_id": "r1"},
                {"type": "response.output_audio.started", "response_id": "r1"},
                {"type": "response.output_audio.done", "response_id": "r1"},   # 收尾,ai_acc 清空
                {"type": "response.output_text.done", "text": "正文全文", "response_id": "r1"},  # 迟到
                {"type": "session.closed"},
            ]
            doubao_ws = FakeDoubaoWs(events=events)
            client_ws = CollectingWebSocket()
            await self._drain(self._run_loop(doubao_ws, client_ws))

            texts = [e["text"] for e in client_ws.events if e["type"] == "assistant_text"]
            self.assertEqual(texts, ["正文"])  # 迟到 done 未产生第二次推送

        asyncio.run(run_test())


if __name__ == "__main__":
    unittest.main()
