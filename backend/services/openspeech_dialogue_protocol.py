"""Volcengine OpenSpeech Dialogue Binary Framing Protocol Encoder/Decoder.

Implements the 4-byte header binary framing protocol for Volcengine Speech
End-to-End Realtime Voice Model (volc.speech.dialog / wss://openspeech.bytedance.com/api/v3/realtime/dialogue).
"""
from __future__ import annotations

import json
import struct
import zlib
from typing import Any, NamedTuple

# Header Constants
PROTOCOL_VERSION_V1 = 0b0001
HEADER_SIZE_4BYTES = 0b0001
BYTE0_HEADER = (PROTOCOL_VERSION_V1 << 4) | HEADER_SIZE_4BYTES  # 0x11

# Message Types (4 bits)
MSG_TYPE_FULL_CLIENT_REQ = 0b0001  # 1
MSG_TYPE_AUDIO_CLIENT_REQ = 0b0010  # 2
MSG_TYPE_FULL_SERVER_RESP = 0b1001  # 9
MSG_TYPE_AUDIO_SERVER_RESP = 0b1011  # 11
MSG_TYPE_ERROR_INFO = 0b1111        # 15

# Serialization Method (4 bits)
SERIALIZATION_RAW = 0b0000
SERIALIZATION_JSON = 0b0001

# Compression Method (4 bits)
COMPRESSION_NONE = 0b0000
COMPRESSION_GZIP = 0b0001


class OpenSpeechFrame(NamedTuple):
    msg_type: int
    msg_flags: int
    serialization: int
    compression: int
    event: int | None
    code: int | None
    sequence: int | None
    session_id: str | None
    payload: bytes


def encode_openspeech_frame(
    msg_type: int,
    payload: bytes | str | dict[str, Any],
    event: int | None = None,
    session_id: str | None = None,
    sequence: int | None = None,
    is_json: bool = False,
    compress: bool = False,
) -> bytes:
    """Encode an OpenSpeech binary protocol frame."""
    if isinstance(payload, dict):
        payload_bytes = json.dumps(payload).encode("utf-8")
        is_json = True
    elif isinstance(payload, str):
        payload_bytes = payload.encode("utf-8")
    else:
        payload_bytes = payload

    if compress and payload_bytes:
        payload_bytes = zlib.compress(payload_bytes)
        compression_method = COMPRESSION_GZIP
    else:
        compression_method = COMPRESSION_NONE

    serialization_method = SERIALIZATION_JSON if is_json else SERIALIZATION_RAW

    # Build flags
    flags = 0
    optional_bytes = bytearray()

    if event is not None:
        flags |= 0b0100  # event flag
        optional_bytes.extend(struct.pack(">I", event))

    if session_id:
        flags |= 0b0001  # session id flag
        sid_bytes = session_id.encode("utf-8")
        optional_bytes.extend(struct.pack(">I", len(sid_bytes)))
        optional_bytes.extend(sid_bytes)

    byte1 = (msg_type << 4) | (flags & 0x0F)
    byte2 = (serialization_method << 4) | (compression_method & 0x0F)
    byte3 = 0x00  # Reserved

    header = bytes([BYTE0_HEADER, byte1, byte2, byte3])
    payload_size = struct.pack(">I", len(payload_bytes))

    return header + bytes(optional_bytes) + payload_size + payload_bytes


def decode_openspeech_frame(data: bytes) -> OpenSpeechFrame:
    """Decode an OpenSpeech binary protocol frame."""
    if len(data) < 8:
        raise ValueError(f"Frame data too short: {len(data)} bytes")

    byte0 = data[0]
    byte1 = data[1]
    byte2 = data[2]

    msg_type = (byte1 >> 4) & 0x0F
    msg_flags = byte1 & 0x0F

    serialization = (byte2 >> 4) & 0x0F
    compression = byte2 & 0x0F

    offset = 4
    event: int | None = None
    code: int | None = None
    sequence: int | None = None
    session_id: str | None = None

    if msg_type == MSG_TYPE_ERROR_INFO:
        if len(data) >= offset + 4:
            code = struct.unpack(">I", data[offset:offset+4])[0]
            offset += 4

    if msg_flags & 0b0100:  # Has event ID
        if len(data) >= offset + 4:
            event = struct.unpack(">I", data[offset:offset+4])[0]
            offset += 4

    if msg_flags & 0b0001:  # Has session ID
        if len(data) >= offset + 4:
            sid_len = struct.unpack(">I", data[offset:offset+4])[0]
            offset += 4
            if len(data) >= offset + sid_len:
                session_id = data[offset:offset+sid_len].decode("utf-8", errors="ignore")
                offset += sid_len

    if len(data) < offset + 4:
        raise ValueError("Corrupt frame header before payload size")

    payload_size = struct.unpack(">I", data[offset:offset+4])[0]
    offset += 4

    payload = data[offset:offset + payload_size]

    if compression == COMPRESSION_GZIP and payload:
        try:
            payload = zlib.decompress(payload)
        except Exception:
            pass

    return OpenSpeechFrame(
        msg_type=msg_type,
        msg_flags=msg_flags,
        serialization=serialization,
        compression=compression,
        event=event,
        code=code,
        sequence=sequence,
        session_id=session_id,
        payload=payload,
    )
