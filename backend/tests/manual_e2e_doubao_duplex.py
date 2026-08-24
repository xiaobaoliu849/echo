"""End-to-end live check: run the real backend duplex path against Volcengine.

Feeds the official demo's whoareyou.wav (16k pcm) as mic audio through
RealtimeVoiceService._run_doubao_session and prints the client-facing events.

Run: python backend/tests/manual_e2e_doubao_duplex.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.realtime_voice_service import RealtimeVoiceService  # noqa: E402

WAV_PATH = Path(r"D:\voicespirit\python3.7_duplex_demo\python3.7_duplex_demo\whoareyou.wav")
CHUNK = 640  # 20ms @ 16k s16le


class FakeClientWs:
    """Minimal stand-in for the FastAPI server-side WebSocket."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.events: list[dict] = []
        self.audio_bytes = bytearray()

    async def send_json(self, payload: dict) -> None:
        self.events.append(dict(payload))
        t = payload.get("type")
        if t == "assistant_audio":
            self.audio_bytes.extend(base64.b64decode(payload.get("audio", "")))
            print(f"  [client<-srv] assistant_audio (+{len(payload.get('audio', ''))} b64 chars)")
        elif t in ("user_transcript", "assistant_text", "error", "session_open",
                   "turn_complete", "interrupted", "agent_progress"):
            extra = {k: v for k, v in payload.items() if k not in ("type", "audio")}
            print(f"  [client<-srv] {t}: {json.dumps(extra, ensure_ascii=False)[:220]}")

    async def send_bytes(self, payload: bytes) -> None:
        pass

    async def receive(self) -> dict:
        item = await self.queue.get()
        return item

    def feed_audio(self, data: bytes) -> None:
        self.queue.put_nowait({"type": "websocket.receive", "bytes": data})


async def main() -> None:
    with wave.open(str(WAV_PATH), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1, (
            f"unexpected wav format: {w.getframerate()}Hz ch={w.getnchannels()}"
        )
        pcm = w.readframes(w.getnframes())
    print(f"loaded {WAV_PATH.name}: {len(pcm)} bytes ({len(pcm)/32000:.1f}s)")

    ws = FakeClientWs()
    service = RealtimeVoiceService()

    async def producer() -> None:
        # feed the question at near-realtime pace, then silence so the server
        # VAD can commit the utterance while we wait for the reply
        pos = 0
        while pos < len(pcm):
            ws.feed_audio(pcm[pos : pos + CHUNK])
            pos += CHUNK
            await asyncio.sleep(0.02)
        print("  [mic] question fed, streaming silence…")
        zero = b"\x00" * CHUNK
        for _ in range(400):  # up to 8s of trailing silence
            ws.feed_audio(zero)
            await asyncio.sleep(0.02)
        ws.queue.put_nowait({"type": "websocket.disconnect"})

    prod_task = asyncio.create_task(producer())
    try:
        await asyncio.wait_for(
            service._run_doubao_session(ws, instructions="你是语音助手，请简短回答。"),
            timeout=45,
        )
    except asyncio.TimeoutError:
        print("TIMEOUT after 45s")
    finally:
        prod_task.cancel()

    types = [e.get("type") for e in ws.events]
    print("\n=== summary ===")
    print("event types:", types)
    ok_open = "session_open" in types
    ok_asr = any(e.get("type") == "user_transcript" and not e.get("interim") for e in ws.events)
    ok_tts = len(ws.audio_bytes) > 1000
    print(f"session_open={ok_open} final_user_transcript={ok_asr} tts_bytes={len(ws.audio_bytes)}")
    print("RESULT:", "PASS" % () if False else ("PASS" if (ok_open and ok_tts) else "FAIL"))


if __name__ == "__main__":
    asyncio.run(main())
