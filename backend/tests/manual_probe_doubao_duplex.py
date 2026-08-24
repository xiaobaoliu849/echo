"""Probe Doubao realtime endpoints with the user's current credentials.

Tries, in order:
  1. OLD endpoint /api/v3/realtime/dialogue  (binary protocol, X-Api-Access-Key)
  2. NEW duplex endpoint /api/v3/duplex/realtime/dialogue (JSON protocol, X-Api-Key)

Run: python backend/tests/manual_probe_doubao_duplex.py
"""
from __future__ import annotations

import asyncio
import base64
import json
import struct
import sys
import uuid

import websockets

APP_ID = "3116450536"
TOKEN = "26d58346-9efa-4dff-9997-a61776b06478"

OLD_URL = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
NEW_URL = "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"

# ---- minimal OpenSpeech binary framing (same as backend protocol module) ----

PROTOCOL_VERSION = 0b0001
HEADER_SIZE = 0b0001
MSG_TYPE_FULL_CLIENT_REQ = 0b0001
MSG_TYPE_AUDIO_CLIENT_REQ = 0b0010
MSG_TYPE_ERROR_INFO = 0b1111
EVENT_START_CONNECTION = 0b0001_0001


def _header(msg_type: int, flags: int = 0) -> bytes:
    hdr = bytearray(4)
    hdr[0] = (PROTOCOL_VERSION << 4) | HEADER_SIZE
    hdr[1] = (msg_type << 4) | flags
    hdr[2] = 0x00  # no compression
    hdr[3] = 0x00
    return bytes(hdr)


def encode_full_client_req(payload: dict, event: int, session_id: str | None = None) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    out = bytearray(_header(MSG_TYPE_FULL_CLIENT_REQ))
    flags = 0b0000 if session_id is None else 0b0011
    out[1] = (MSG_TYPE_FULL_CLIENT_REQ << 4) | flags
    # event (i32)
    out += struct.pack(">i", event)
    if session_id is not None:
        sid = session_id.encode("utf-8")
        out += struct.pack(">H", len(sid)) + sid
    out += struct.pack(">i", len(body)) + body
    return bytes(out)


def parse_frame(raw: bytes):
    if len(raw) < 4:
        return ("short", raw[:32])
    msg_type = (raw[1] >> 4) & 0x0F
    flags = raw[1] & 0x0F
    pos = 4
    event = code = None
    session_id = ""
    payload_size = 0
    payload = b""
    if flags in (0b0001, 0b0011):  # has event
        (event,) = struct.unpack_from(">i", raw, pos)
        pos += 4
    if flags in (0b0010, 0b0011):  # has session id
        (sid_len,) = struct.unpack_from(">H", raw, pos)
        pos += 2
        session_id = raw[pos : pos + sid_len].decode("utf-8", "replace")
        pos += sid_len
    if msg_type == MSG_TYPE_ERROR_INFO:
        (code,) = struct.unpack_from(">i", raw, pos)
        pos += 4
    if pos + 4 <= len(raw):
        (payload_size,) = struct.unpack_from(">i", raw, pos)
        pos += 4
        payload = raw[pos : pos + max(payload_size, 0)]
    return {
        "msg_type": msg_type,
        "flags": flags,
        "event": event,
        "code": code,
        "session_id": session_id,
        "payload": payload[:800].decode("utf-8", "replace"),
    }


async def probe_old() -> None:
    print("=" * 70)
    print("[PROBE 1] OLD binary endpoint:", OLD_URL)
    headers = {
        "X-Api-App-ID": APP_ID,
        "X-Api-Access-Key": TOKEN,
        "X-Api-Resource-Id": "volc.speech.dialog",
        "X-Api-App-Key": "PlgvMymc7f3tQnJ6",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    try:
        async with websockets.connect(
            OLD_URL, additional_headers=headers, ping_interval=None, max_size=2**22,
        ) as ws:
            logid = ws.response.headers.get("X-Tt-Logid") if hasattr(ws.response, "headers") else None
            print("  connected OK, logid =", logid)
            await ws.send(encode_full_client_req({}, event=EVENT_START_CONNECTION))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=10)
                info = parse_frame(raw if isinstance(raw, bytes) else raw.encode())
                print("  frame:", json.dumps(info, ensure_ascii=False)[:500])
                if isinstance(info, dict) and info.get("event") is not None:
                    break
    except Exception as exc:
        status = getattr(exc, "status_code", None) or getattr(
            getattr(exc, "response", None), "status_code", None
        )
        body = getattr(getattr(exc, "response", None), "body", None)
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        if status:
            print(f"  http_status={status} body={body!r}")


async def probe_new() -> None:
    print("=" * 70)
    print("[PROBE 2] NEW duplex JSON endpoint:", NEW_URL)
    for label, headers in (
        ("X-Api-Key", {"X-Api-Key": TOKEN}),
        ("Authorization Bearer", {"Authorization": f"Bearer {TOKEN}"}),
    ):
        print(f"  --- auth via {label} ---")
        try:
            async with websockets.connect(
                NEW_URL, additional_headers=headers, ping_interval=None, max_size=2**22,
            ) as ws:
                logid = ws.response.headers.get("X-Tt-Logid") if hasattr(ws.response, "headers") else None
                print("  connected OK, logid =", logid)
                session_evt = {
                    "type": "session.create",
                    "event_id": "evt_probe_1",
                    "session": {
                        "id": str(uuid.uuid4()),
                        "model": "1.2.6.1",
                        "instructions": "你是语音助手。",
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
                        "dialog": {"extra": {"enable_loudness_norm": True}},
                    },
                }
                await ws.send(json.dumps(session_evt, ensure_ascii=False))
                for _ in range(5):
                    raw = await asyncio.wait_for(ws.recv(), timeout=10)
                    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
                    evt = {}
                    try:
                        evt = json.loads(text)
                    except Exception:
                        pass
                    print("  recv:", (evt.get("type") or "?"), text[:400])
                    t = evt.get("type")
                    if t in ("session.created", "error"):
                        break
                break
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(
                getattr(exc, "response", None), "status_code", None
            )
            body = getattr(getattr(exc, "response", None), "body", None)
            print(f"  FAILED: {type(exc).__name__}: {exc}")
            if status:
                print(f"  http_status={status} body={body!r}")


async def main() -> None:
    await probe_old()
    await probe_new()
    print("=" * 70)
    print("done")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
