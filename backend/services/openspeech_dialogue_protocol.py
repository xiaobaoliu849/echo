"""Volcengine OpenSpeech Dialogue Binary Framing Protocol Encoder/Decoder.

Implements the 4-byte header binary framing protocol for the Volcengine Speech
End-to-End Realtime Voice Model (volc.speech.dialog /
wss://openspeech.bytedance.com/api/v3/realtime/dialogue).

Frame layout (per the official RealtimeAPI docs):

    byte0: Protocol Version (0b0001) << 4 | Header Size (0b0001)  → 0x11
    byte1: Message Type << 4 | Message type specific flags
    byte2: Serialization method << 4 | Compression method
    byte3: 0x00 (reserved)

Optional fields follow the header in this exact order (presence driven by
flags / message type / event class):

    code        4B  – only for error frames (msg type 0b1111)
    sequence    4B  – flags 0b0001 (positive) / 0b0011 (negative, last packet)
    event       4B  – flags 0b0100
    connect id  4B size + bytes – only for connection-class events
    session id  4B size + bytes – for session-class events (NOT flag-driven;
                      the session-id flag bit does not exist in this protocol)

Then: payload size (4B) + payload.
"""
from __future__ import annotations

import gzip
import json
import struct
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

# Message type specific flags (4 bits)
FLAG_POSITIVE_SEQUENCE = 0b0001
FLAG_LAST_WITHOUT_SEQUENCE = 0b0010
FLAG_NEGATIVE_SEQUENCE = 0b0011
FLAG_WITH_EVENT = 0b0100

# Serialization Method (4 bits)
SERIALIZATION_RAW = 0b0000
SERIALIZATION_JSON = 0b0001

# Compression Method (4 bits)
COMPRESSION_NONE = 0b0000
COMPRESSION_GZIP = 0b0001

# ---------------------------------------------------------------------------
# Event IDs (实时对话事件)
# ---------------------------------------------------------------------------
# Client → server
EVENT_START_CONNECTION = 1
EVENT_FINISH_CONNECTION = 2
EVENT_START_SESSION = 100
EVENT_FINISH_SESSION = 102
EVENT_TASK_REQUEST = 200          # audio upload
EVENT_UPDATE_CONFIG = 201
EVENT_SAY_HELLO = 300
EVENT_END_ASR = 400               # push_to_talk audio end signal
EVENT_CHAT_TTS_TEXT = 500
EVENT_CHAT_TEXT_QUERY = 501
EVENT_CHAT_RAG_TEXT = 502
EVENT_CLIENT_INTERRUPT = 515

# Server → client
EVENT_CONNECTION_STARTED = 50
EVENT_CONNECTION_FAILED = 51
EVENT_CONNECTION_FINISHED = 52
EVENT_SESSION_STARTED = 150
EVENT_SESSION_FINISHED = 152
EVENT_SESSION_FAILED = 153
EVENT_USAGE_RESPONSE = 154
EVENT_CONFIG_UPDATED = 251
EVENT_TTS_SENTENCE_START = 350
EVENT_TTS_SENTENCE_END = 351
EVENT_TTS_RESPONSE = 352          # audio payload
EVENT_TTS_ENDED = 359
EVENT_ASR_INFO = 450              # first token recognized → barge-in signal
EVENT_ASR_RESPONSE = 451
EVENT_ASR_ENDED = 459
EVENT_CHAT_RESPONSE = 550
EVENT_CHAT_TEXT_QUERY_CONFIRMED = 553
EVENT_CHAT_ENDED = 559
EVENT_DIALOG_COMMON_ERROR = 599

# Connection-class events carry a connect id instead of a session id.
CONNECT_EVENT_IDS = frozenset({
    EVENT_START_CONNECTION,
    EVENT_FINISH_CONNECTION,
    EVENT_CONNECTION_STARTED,
    EVENT_CONNECTION_FAILED,
    EVENT_CONNECTION_FINISHED,
})


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
    connect_id: str | None = None


def encode_openspeech_frame(
    msg_type: int,
    payload: bytes | str | dict[str, Any],
    event: int | None = None,
    session_id: str | None = None,
    connect_id: str | None = None,
    sequence: int | None = None,
    is_json: bool = False,
    compress: bool = False,
) -> bytes:
    """Encode an OpenSpeech binary protocol frame.

    ``session_id`` / ``connect_id`` are length-prefixed fields appended after
    the event field; unlike ``event``/``sequence`` they are not announced via
    flag bits — their presence is implied by the event class.
    """
    if isinstance(payload, dict):
        payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        is_json = True
    elif isinstance(payload, str):
        payload_bytes = payload.encode("utf-8")
    else:
        payload_bytes = payload

    if compress and payload_bytes:
        payload_bytes = gzip.compress(payload_bytes)
        compression_method = COMPRESSION_GZIP
    else:
        compression_method = COMPRESSION_NONE

    serialization_method = SERIALIZATION_JSON if is_json else SERIALIZATION_RAW

    flags = 0
    optional_bytes = bytearray()

    if sequence is not None:
        if sequence < 0:
            flags |= FLAG_NEGATIVE_SEQUENCE
        else:
            flags |= FLAG_POSITIVE_SEQUENCE
        optional_bytes.extend(struct.pack(">i", sequence))

    if event is not None:
        flags |= FLAG_WITH_EVENT
        optional_bytes.extend(struct.pack(">I", event))

    if connect_id:
        cid_bytes = connect_id.encode("utf-8")
        optional_bytes.extend(struct.pack(">I", len(cid_bytes)))
        optional_bytes.extend(cid_bytes)

    if session_id:
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
    connect_id: str | None = None

    if msg_type == MSG_TYPE_ERROR_INFO:
        if len(data) >= offset + 4:
            code = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4

    seq_flags = msg_flags & 0b0011
    if seq_flags in (FLAG_POSITIVE_SEQUENCE, FLAG_NEGATIVE_SEQUENCE):
        if len(data) >= offset + 4:
            sequence = struct.unpack(">i", data[offset:offset + 4])[0]
            offset += 4

    if msg_flags & FLAG_WITH_EVENT:
        if len(data) >= offset + 4:
            event = struct.unpack(">I", data[offset:offset + 4])[0]
            offset += 4

    # connect id / session id presence is implied by the event class.
    if event is not None and len(data) >= offset + 4:
        id_len = struct.unpack(">I", data[offset:offset + 4])[0]
        # After the id there must still be room for the 4-byte payload size;
        # otherwise these 4 bytes ARE the payload size (no id field present).
        if id_len <= len(data) - offset - 8:
            offset += 4
            if id_len > 0:
                id_value = data[offset:offset + id_len].decode("utf-8", errors="ignore")
                if event in CONNECT_EVENT_IDS:
                    connect_id = id_value
                else:
                    session_id = id_value
                offset += id_len

    if len(data) < offset + 4:
        raise ValueError("Corrupt frame header before payload size")

    payload_size = struct.unpack(">I", data[offset:offset + 4])[0]
    offset += 4

    payload = data[offset:offset + payload_size]

    if compression == COMPRESSION_GZIP and payload:
        try:
            payload = gzip.decompress(payload)
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
        connect_id=connect_id,
    )
