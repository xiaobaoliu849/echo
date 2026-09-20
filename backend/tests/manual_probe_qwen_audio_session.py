"""Manual session probe for the DashScope Qwen-Audio realtime models.

Not collected by pytest (no ``test_`` prefix). Run it from ``backend/`` with a
configured DashScope workspace:

    python tests/manual_probe_qwen_audio_session.py
    python tests/manual_probe_qwen_audio_session.py qwen-audio-3.0-realtime-plus

Qwen-Audio runs on Echo's own raw WebSocket client (not the DashScope SDK), so
this probe captures the exact ``session.update`` that
``DashScopeAudioRealtimeConversation`` sends — voice, ``turn_detection``,
``input_audio_transcription``, ``max_history_turns`` and ``tools`` — and replays
it against the real endpoint, printing every server frame.

It answers the two questions a model swap raises:

  * does the model accept our payload at all (``session.updated`` vs ``error``),
  * and what does the server echo back / normalise (voice, VAD values, ASR)?

``qwen-audio-3.1-realtime-plus`` keeps 3.0's event protocol, so the model id and
the voice are the only intended differences; this probe is how that claim gets
checked instead of assumed.
"""
import asyncio
import json
import sys
import time

import websockets

sys.path.insert(0, ".")

from services.config_loader import BackendConfig  # noqa: E402
from services.realtime_constants import (  # noqa: E402
    _normalize_dashscope_realtime_voice,
)
from services.realtime_dashscope_client import (  # noqa: E402
    DashScopeAudioRealtimeConversation,
)

MODELS = ("qwen-audio-3.1-realtime-plus", "qwen-audio-3.0-realtime-plus")
INSTRUCTIONS = "你是 Echo 的实时语音助手，请用自然口语回答。"
SETTLE_SECONDS = 6.0


def adapter_session_payload(model: str) -> dict:
    """Capture the exact first ``session.update`` the adapter sends for *model*."""
    conversation = DashScopeAudioRealtimeConversation(
        model=model,
        api_key="probe",
        url="wss://probe.invalid/api-ws/v1/realtime",
        callback=None,  # type: ignore[arg-type]
    )
    sent: list[dict] = []
    conversation._send_event = sent.append  # type: ignore[method-assign]
    conversation.update_session(
        voice=_normalize_dashscope_realtime_voice(model, ""),
        instructions=INSTRUCTIONS,
        tools=[],
    )
    if not sent:
        raise RuntimeError("adapter sent no session.update")
    return sent[0]["session"]


async def run_variant(label: str, model: str, session: dict, key: str, url: str) -> None:
    print(f"\n=== {label} | model={model}")
    print("  session:", json.dumps(session, ensure_ascii=False))
    started = time.monotonic()
    saw_session_created = False
    try:
        async with websockets.connect(
            f"{url}?model={model}",
            additional_headers={"Authorization": f"Bearer {key}", "user-agent": "Echo/AudioProbe"},
            max_size=16777216,
            ping_interval=None,
        ) as ws:
            await ws.send(json.dumps({"type": "session.update", "session": session}))
            deadline = time.monotonic() + SETTLE_SECONDS
            while time.monotonic() < deadline:
                try:
                    raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                except asyncio.TimeoutError:
                    continue
                kind = raw.get("type", "")
                print(f"  {time.monotonic() - started:6.2f}s  {kind or 'untyped frame'}")
                if not kind:
                    print("    raw:", json.dumps(raw, ensure_ascii=False)[:400])
                if kind == "session.created":
                    saw_session_created = True
                elif kind == "session.updated":
                    echo = raw.get("session") or {}
                    print("    accepted:", json.dumps({
                        "voice": echo.get("voice"),
                        "modalities": echo.get("modalities"),
                        "input_audio_format": echo.get("input_audio_format"),
                        "input_audio_transcription": echo.get("input_audio_transcription"),
                        "turn_detection": echo.get("turn_detection"),
                        "max_history_turns": echo.get("max_history_turns"),
                        "tools": len(echo.get("tools") or []),
                    }, ensure_ascii=False))
                elif kind == "error":
                    print("    ERROR:", json.dumps(raw.get("error") or raw, ensure_ascii=False))
                    break
            try:
                await ws.send(json.dumps({"type": "session.finish"}))
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        stage = "after session.created" if saw_session_created else "during handshake"
        print(f"  connection lost {stage}: {type(exc).__name__}: {exc}")
        return
    print(f"  closed after {time.monotonic() - started:.2f}s")


def main() -> None:
    config = BackendConfig()
    settings = config.get_all()
    key = str(settings["api_keys"]["dashscope_api_key"])
    url = str(settings["realtime_api_urls"]["DashScope"])
    if not key or not url:
        print("DashScope API key / realtime URL not configured; nothing to probe.")
        return
    print("url:", url)
    models = tuple(arg for arg in sys.argv[1:] if not arg.startswith("--")) or MODELS
    for model in models:
        try:
            session = adapter_session_payload(model)
        except Exception as exc:  # noqa: BLE001
            print(f"\n=== {model}: could not build the adapter payload: {exc}")
            continue
        variants = [
            ("A. adapter payload", session),
            ("B. adapter payload without input_audio_transcription",
             {k: v for k, v in session.items() if k != "input_audio_transcription"}),
        ]
        for label, payload in variants:
            try:
                asyncio.run(run_variant(label, model, payload, key, url))
            except Exception as exc:  # noqa: BLE001
                print("  variant failed:", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
