"""Manual session probe for the DashScope Omni Realtime models.

Not collected by pytest (no ``test_`` prefix). Run it from ``backend/`` with a
configured DashScope workspace:

    python tests/manual_probe_omni_session.py
    python tests/manual_probe_omni_session.py qwen3.8-omni-plus-realtime

Why this exists: ``qwen3.8-omni-flash-realtime`` is the shipped DashScope default
but the vendor's Realtime reference still documents only the 3.5 generation (see
``docs/Qwen_3_8_Omni_Realtime.md``), so the wire id and the accepted session
shape are unverified. When a model is unknown or a session field is rejected the
server replies with an ``error`` frame and closes the socket, which in the app
looks like "the call opens and immediately closes".

The probe prints every raw server frame for these variants per model:

  B. the exact payload the app sends, minus ``input_audio_transcription`` — the
     3.5-era ASR model id is the field our own 3.8 LiveTranslate adapter had to
     stop sending,
  C. the exact payload the app sends (captured from the adapter itself),
  D. the minimal session (``modalities`` + ``voice``), which separates "this
     account cannot use the model" from "this session field is rejected".

Read the output as: which model ids even get ``session.created``, which ones get
``session.updated`` (configured and usable), which ones answer ``error``, and
which ones are dropped with no error frame at all.

Pass ``--minimal`` to run only variant D, which is the cheap way to tell an
account/rollout problem from a session-schema problem.
"""
import asyncio
import json
import sys
import time

import websockets

sys.path.insert(0, ".")

from services.config_loader import BackendConfig  # noqa: E402
from services.realtime_dashscope_provider import DashScopeRealtimeMixin  # noqa: E402

MODELS = ("qwen3.8-omni-flash-realtime", "qwen3.5-omni-plus-realtime")
VOICE = "Tina"
INSTRUCTIONS = "你是 Echo 的实时语音助手，请用自然口语回答。"
SETTLE_SECONDS = 8.0
# The smallest session a realtime model can be configured with. If a model
# survives this but not the full adapter payload, the fields are the problem; if
# it drops here too, the model is not usable for this account.
MINIMAL_SESSION = {"modalities": ["audio", "text"], "voice": VOICE}


def adapter_session_payload(model: str) -> dict:
    """Capture the exact ``session`` dict the app sends for *model*.

    The DashScope SDK builds the payload from its own kwargs, so instead of
    duplicating that shape here we instantiate the real SDK conversation, stub
    out its send, and let the adapter configure it.
    """
    import dashscope
    from dashscope.audio.qwen_omni import OmniRealtimeCallback, OmniRealtimeConversation

    class _NoopCallback(OmniRealtimeCallback):
        def on_open(self) -> None:
            return None

        def on_event(self, response) -> None:  # noqa: ANN001
            return None

        def on_close(self, close_status_code, close_msg) -> None:  # noqa: ANN001
            return None

    dashscope.api_key = "probe"
    conversation = OmniRealtimeConversation(
        model=model,
        callback=_NoopCallback(),
        url="wss://probe.invalid/api-ws/v1/realtime",
    )
    sent: list[dict] = []
    conversation._OmniRealtimeConversation__send_str = (  # type: ignore[attr-defined]
        lambda data, enable_log=True: sent.append(json.loads(data))
    )
    DashScopeRealtimeMixin._configure_dashscope_conversation(
        conversation, voice=VOICE, instructions=INSTRUCTIONS
    )
    if not sent:
        raise RuntimeError("adapter did not send a session.update")
    return sent[0]["session"]


async def run_variant(label: str, model: str, session: dict, key: str, url: str) -> None:
    print(f"\n=== {label} | model={model}")
    print("  session:", json.dumps(session, ensure_ascii=False))
    started = time.monotonic()
    configured = False
    try:
        async with websockets.connect(
            f"{url}?model={model}",
            additional_headers={"Authorization": f"Bearer {key}", "user-agent": "Echo/OmniProbe"},
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
                    configured = True
                if kind == "session.updated":
                    # The echo tells us what the server actually accepted.
                    echo = (raw.get("session") or {})
                    print("    accepted:", json.dumps({
                        "voice": echo.get("voice"),
                        "modalities": echo.get("modalities") or echo.get("output_modalities"),
                        "input_audio_format": echo.get("input_audio_format"),
                        "audio": echo.get("audio"),
                        "input_audio_transcription": echo.get("input_audio_transcription"),
                        "turn_detection": echo.get("turn_detection"),
                    }, ensure_ascii=False))
                elif kind == "error":
                    print("    ERROR:", json.dumps(raw.get("error") or raw, ensure_ascii=False))
                    break
            try:
                await ws.send(json.dumps({"type": "session.finish"}))
            except Exception:
                pass
    except Exception as exc:  # noqa: BLE001
        # An unknown model is refused during the WS handshake; a model the
        # account cannot use is accepted (session.created) and then dropped with
        # no error frame at all, which is what this branch reports on.
        stage = "after session.created" if configured else "during handshake"
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
    # The workspace id lives in the URL, never in the API key.
    print("url:", url)
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    minimal_only = "--minimal" in sys.argv
    models = tuple(args) or MODELS
    for model in models:
        if minimal_only:
            variants = [("D. minimal session", dict(MINIMAL_SESSION))]
        else:
            try:
                session = adapter_session_payload(model)
            except Exception as exc:  # noqa: BLE001
                print(f"\n=== {model}: could not build the adapter payload: {exc}")
                continue
            variants = [
                (f"C. adapter payload ({model})", session),
                ("B. adapter payload without input_audio_transcription",
                 {k: v for k, v in session.items() if k != "input_audio_transcription"}),
                ("D. minimal session", dict(MINIMAL_SESSION)),
            ]
        for label, payload in variants:
            try:
                asyncio.run(run_variant(label, model, payload, key, url))
            except Exception as exc:  # noqa: BLE001
                print("  variant failed:", type(exc).__name__, exc)


if __name__ == "__main__":
    main()
