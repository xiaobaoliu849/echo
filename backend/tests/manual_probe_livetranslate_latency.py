"""Manual latency probe for qwen3.8-livetranslate-flash-realtime.

Not collected by pytest (no ``test_`` prefix). Run it from ``backend/`` with a
configured DashScope workspace:

    python tests/manual_probe_livetranslate_latency.py [sample.pcm] [--repeat]

Any mono, 16 kHz, signed-16-bit, header-less PCM file works, for example:

    ffmpeg -i speech.mp3 -ac 1 -ar 16000 -f s16le temp_audio/latency/probe_16k.pcm

``backend/temp_audio/`` is git-ignored, so the sample is not committed.

It streams a 16 kHz mono PCM sample at wall-clock pace while reading the socket
concurrently, so every timestamp is a real arrival time. Each run compares the
server's own turn detection against the shipped adapter payload
(``QWEN_LIVETRANSLATE_38_TURN_DETECTION``) and prints, for each variant, when
the turn closed and when the source transcript / translation settled relative
to the end of the speech.

Measured 2026-09-20 on a 5.9 s utterance, server default (2500 ms silence)
versus the shipped 500 ms: the source transcript only started arriving 7.2–10.8 s
into the stream (after the turn closed) and its final fragment landed
3.5–14.9 s after the speaker stopped, whereas with 500 ms the text streamed
during speech and settled 0.5–1.3 s after the speaker stopped.
"""
import asyncio
import base64
import json
import random
import sys
import time

import websockets

sys.path.insert(0, ".")

from services.config_loader import BackendConfig  # noqa: E402

MODEL = "qwen3.8-livetranslate-flash-realtime"
DEFAULT_PCM_PATH = "temp_audio/latency/probe_16k.pcm"
CHUNK = 3200  # 100 ms of 16k mono s16
PCM_PATH = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PCM_PATH


def ADAPTER_INPUT():
    """The exact ``audio.input`` the shipped adapter sends for 3.8."""
    from services.realtime_dashscope_client import DashScopeLiveTranslateConversation

    conversation = DashScopeLiveTranslateConversation(
        model=MODEL, api_key="probe", url="wss://example", callback=None)
    sent = []
    conversation._send_event = sent.append
    conversation.update_session(voice="Tina", target_language="en")
    payload = sent[0]["session"]
    print("  adapter session payload:", json.dumps(payload, ensure_ascii=False))
    return {
        "turn_detection": payload["audio"]["input"]["turn_detection"],
        "format": payload["audio"]["input"]["format"],
    }


def base_session():
    return {
        "output_modalities": ["text", "audio"],
        "translation": {"language": "en"},
        "audio": {
            "input": {"format": {"type": "pcm", "sample_rate": 16000}},
            "output": {
                "format": {"type": "pcm", "sample_rate": 24000},
                "voice": "Tina",
            },
        },
    }


async def run_variant(label, extra_input, key, url):
    session = base_session()
    session["audio"]["input"].update(extra_input)
    print(f"\n=== {label} :: input = {json.dumps(session['audio']['input'], ensure_ascii=False)}")
    events = []          # (arrival_rel_to_audio_start, kind, payload)
    audio_pos = 0.0      # seconds of audio sent so far
    audio_start = time.monotonic()

    async with websockets.connect(
        f"{url}?model={MODEL}",
        additional_headers={"Authorization": f"Bearer {key}", "user-agent": "Echo/LatencyProbe"},
        max_size=16777216,
        ping_interval=None,
    ) as ws:
        await ws.send(json.dumps({"type": "session.update", "session": session}))
        configured = False
        deadline = time.monotonic() + 15
        while not configured and time.monotonic() < deadline:
            raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            kind = raw.get("type")
            if kind == "session.updated":
                configured = True
                print("  session.updated:", json.dumps(
                    (raw.get("session") or {}).get("audio", {}).get("input", {}).get("turn_detection"),
                    ensure_ascii=False))
            elif kind == "error":
                print("  ERROR:", json.dumps(raw.get("error"), ensure_ascii=False))
                return None
        if not configured:
            print("  no session.updated -> abort")
            return None

        with open(PCM_PATH, "rb") as source:
            pcm = source.read()
        # A real microphone never sends absolute zeros: its noise floor keeps
        # streaming while the user is silent. Use low-level noise so the VAD's
        # silence detection sees what it sees in the app.
        random.seed(7)
        floor = b"".join(
            int(random.gauss(0, 25)).to_bytes(2, "little", signed=True) for _ in range(16000 * 3)
        )
        preroll = floor[:3200]      # 100 ms
        tail = floor[3200:]         # remaining ~2.9 s

        async def reader():
            while True:
                raw = json.loads(await ws.recv())
                events.append((time.monotonic() - audio_start, raw.get("type", ""), raw))
                if raw.get("type") == "session.finished":
                    return

        reader_task = asyncio.create_task(reader())
        sent = 0
        for payload in (preroll, pcm, tail):
            for offset in range(0, len(payload), CHUNK):
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(payload[offset:offset + CHUNK]).decode("ascii"),
                }))
                sent += 1
                # Keep the stream at wall-clock pace so every arrival timestamp
                # can be compared against the audio position it belongs to.
                await asyncio.sleep(max(0.0, audio_start + 0.1 * sent - time.monotonic()))
                audio_pos = time.monotonic() - audio_start
        speech_end = audio_pos - (len(tail) / 32000)  # trailing noise floor is not speech
        await ws.send(json.dumps({"type": "session.finish"}))
        try:
            await asyncio.wait_for(reader_task, timeout=20)
        except asyncio.TimeoutError:
            reader_task.cancel()
            print("  timeout waiting for session.finished (socket stayed open)")

    def first(kind):
        return next((t for t, k, _ in events if k == kind), None)

    asr = [(t, raw.get("delta", "")) for t, k, raw in events
           if k == "conversation.item.input_audio_transcription.delta"]
    tr = [(t, raw.get("delta", "")) for t, k, raw in events
          if k in ("response.text.delta", "response.audio_transcript.delta")]
    print(f"  speech window 0.10s..{speech_end:.2f}s; audio end {audio_pos:.2f}s")
    for kind in ("conversation.item.input_audio_transcription.completed", "response.done",
                 "session.finished"):
        t = first(kind)
        if t is not None:
            print(f"  >>> {kind:52s} after speech end: {t - speech_end:+.2f}s")
    print(f"  ASR deltas: {len(asr)}"
          + (f"; first {asr[0][0]:.2f}s (speech +{asr[0][0] - 0.1:.2f}s)"
             f"; last {asr[-1][0]:.2f}s (speech end +{asr[-1][0] - speech_end:.2f}s)"
             if asr else "")
          + (f"; during-speech share "
             f"{sum(1 for t, _ in asr if t <= speech_end)}/{len(asr)}" if asr else ""))
    print("  ASR text:", "".join(t for _, t in asr).strip())
    for kind in ("input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped",
                 "conversation.item.input_audio_transcription.completed",
                 "response.created", "response.text.done", "response.audio_transcript.done",
                 "response.done", "session.finished"):
        t = first(kind)
        if t is not None:
            print(f"  {kind:52s} {t:6.2f}s (speech end {t - speech_end:+5.2f}s)")
    print(f"  translation deltas: {len(tr)}"
          + (f"; first {tr[0][0]:.2f}s (speech end {tr[0][0] - speech_end:+5.2f}s)"
             f"; last {tr[-1][0]:.2f}s" if tr else ""))
    print("  translation:")
    print("   ", "".join(t for _, t in tr).strip())
    return events


def main():
    cfg = BackendConfig()
    all_s = cfg.get_all()
    key = str(all_s["api_keys"]["dashscope_api_key"])
    url = str(all_s["realtime_api_urls"]["DashScope"])
    # Workspace id in the URL is configuration, never the API key.
    print("url:", url)
    variants = [
        ("baseline", {}, "A. server default (no turn_detection)"),
        ("adapter", ADAPTER_INPUT(), "B. shipped adapter payload"),
    ]
    repeat = 2 if "--repeat" in sys.argv else 1
    for _ in range(repeat):
        for _, extra, label in variants:
            try:
                asyncio.run(run_variant(label, extra, key, url))
            except Exception as exc:  # noqa: BLE001
                print("  variant failed:", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
