"""Dump RAW Doubao duplex downlink events to verify transcript semantics.

Answers three questions with live traffic:
  1. Are ``input_audio_transcription.delta`` payloads cumulative snapshots
     (official web demo treats them as full replacements) or increments?
  2. Do ``response.output_text.delta`` events arrive BEFORE
     ``response.output_audio.started`` (i.e. inside the current blanket
     suppression window)?
  3. Is ``response.output_text.done.text`` complete relative to the sum of
     deltas?

Run: python backend/tests/manual_probe_doubao_events.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
import uuid
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import websockets  # noqa: E402

from services.config_loader import BackendConfig  # noqa: E402
from services.realtime_constants import DEFAULT_DOUBAO_DUPLEX_ENDPOINT  # noqa: E402
from services.doubao_asr_provider import _get_websockets_header_kwargs  # noqa: E402

WAV_PATH = Path(r"D:\voicespirit\python3.7_duplex_demo\python3.7_duplex_demo\whoareyou.wav")
CHUNK = 640  # 20ms @ 16k s16le

_t0 = time.perf_counter()


def ts() -> str:
    return f"{(time.perf_counter() - _t0) * 1000:8.1f}ms"


async def main() -> None:
    config = BackendConfig()
    api_key = str(config.get_setting("doubao_access_token", "") or "").strip()
    if not api_key:
        print("no doubao_access_token configured")
        return

    with wave.open(str(WAV_PATH), "rb") as w:
        pcm = w.readframes(w.getnframes())
    print(f"loaded {WAV_PATH.name}: {len(pcm) / 32000:.1f}s")

    headers = {"X-Api-Key": api_key}
    kwargs = {"max_size": 2**24, "ping_interval": 30, "ping_timeout": 30}
    kwargs.update(_get_websockets_header_kwargs(headers))

    asr_snapshots: list[str] = []          # delta payload verbatim
    text_deltas: list[tuple[float, str, str]] = []  # (ts_ms, response_id, delta)
    audio_started_ts: list[tuple[float, str]] = []
    done_text_by_resp: dict[str, str] = {}
    final_transcript = ""
    order: list[str] = []

    async with websockets.connect(DEFAULT_DOUBAO_DUPLEX_ENDPOINT, **kwargs) as ws:
        await ws.send(json.dumps({
            "type": "session.create",
            "event_id": f"evt_{uuid.uuid4().hex[:12]}",
            "session": {
                "model": "1.2.6.1",
                "instructions": "你是语音助手，请简短回答。",
                "audio": {
                    "input": {"format": {"type": "pcm", "rate": 16000}},
                    "output": {
                        "format": {"type": "pcm_s16le", "rate": 24000},
                        "voice": "zh_female_xiaohe_jupiter_bigtts",
                    },
                },
            },
            "extension": {
                "asr": {"extra": {}},
                "tts": {"extra": {}},
                "dialog": {"extra": {}},
            },
        }, ensure_ascii=False))

        async def feed_audio() -> None:
            pos = 0
            while pos < len(pcm):
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(pcm[pos:pos + CHUNK]).decode("ascii"),
                }))
                pos += CHUNK
                await asyncio.sleep(0.02)
            zero = b"\x00" * CHUNK
            end = time.perf_counter() + 12.0
            while time.perf_counter() < end:
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(zero).decode("ascii"),
                }))
                await asyncio.sleep(0.02)

        feeder = asyncio.create_task(feed_audio())

        try:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=15.0)
                except asyncio.TimeoutError:
                    print("[probe] no downlink for 15s, stopping receive loop")
                    break
                now_ms = (time.perf_counter() - _t0) * 1000
                text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                try:
                    evt = json.loads(text)
                except Exception:
                    continue
                etype = str(evt.get("type") or "")

                if etype == "response.output_audio.delta":
                    continue  # too noisy
                snippet = json.dumps(evt, ensure_ascii=False)
                if len(snippet) > 300:
                    snippet = snippet[:300] + "…"
                print(f"[{now_ms:9.1f}ms] {etype} {snippet}")

                if etype == "session.closed":
                    break
                if etype == "error":
                    break

                if etype == "conversation.item.input_audio_transcription.delta":
                    asr_snapshots.append(str(evt.get("delta") or ""))
                    order.append(f"asr_delta#{len(asr_snapshots)}")
                elif etype == "conversation.item.input_audio_transcription.completed":
                    final_transcript = str(
                        evt.get("transcript") or evt.get("text") or ""
                    )
                    order.append("asr_completed")
                elif etype == "response.output_text.delta":
                    rid = str(evt.get("response_id") or "")
                    text_deltas.append((now_ms, rid, str(evt.get("delta") or "")))
                    order.append(f"text_delta({rid[:8]})")
                elif etype == "response.output_audio.started":
                    audio_started_ts.append((now_ms, str(evt.get("response_id") or "")))
                    order.append(f"audio_started({str(evt.get('response_id') or '')[:8]})")
                elif etype == "response.output_text.done":
                    done_text_by_resp[str(evt.get("response_id") or "")] = str(evt.get("text") or "")
                    order.append(f"text_done({str(evt.get('response_id') or '')[:8]})")
        finally:
            feeder.cancel()

    print("\n=== event order ===")
    print(" ".join(order))

    print("\n=== Q1: ASR delta semantics ===")
    acc_incr = ""
    for i, snap in enumerate(asr_snapshots):
        print(f"  delta[{i}] = {snap!r}")
    incremental_sum = "".join(asr_snapshots)
    print(f"  completed.transcript = {final_transcript!r}")
    print(f"  'incremental' join   = {incremental_sum!r}")
    last_snapshot = asr_snapshots[-1] if asr_snapshots else ""
    match_snapshot = last_snapshot.strip() == final_transcript.strip()
    print(f"  => cumulative-snapshot hypothesis (last delta == final): {match_snapshot}")

    print("\n=== Q2/Q3: reply text ordering & completeness ===")
    started_cut = audio_started_ts[0][0] if audio_started_ts else None
    before = "".join(d for (t, _, d) in text_deltas if started_cut is not None and t < started_cut)
    after = "".join(d for (t, _, d) in text_deltas if started_cut is None or t >= started_cut)
    all_text = "".join(d for (_, _, d) in text_deltas)
    done_all = "".join(done_text_by_resp.values())
    print(f"  text deltas total={len(text_deltas)} chars={len(all_text)}")
    print(f"  chars BEFORE first audio.started (= suppressed today): {len(before)} {before!r}")
    print(f"  chars AFTER  first audio.started:                     {len(after)} {after!r}")
    print(f"  done.text total chars: {len(done_all)} {done_all!r}")
    print(f"  => done covers suppressed head (done.startswith(before)): "
          f"{done_all.startswith(before) if before else 'n/a'}")
    print(f"  => sum(deltas) == done.text: {all_text == done_all}")


if __name__ == "__main__":
    asyncio.run(main())
