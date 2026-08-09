from __future__ import annotations

import asyncio
import gzip
import json
import logging
import struct
import uuid
from pathlib import Path

try:
    import websockets
except ImportError:
    websockets = None

logger = logging.getLogger(__name__)

DOUBAO_ASR_BIGMODEL_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel"
DOUBAO_ASR_BIGMODEL_ASYNC_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
DOUBAO_ASR_NOSTREAM_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_nostream"

# Resource IDs
DOUBAO_ASR_1_RESOURCE = "volc.bigasr.sauc.duration"
DOUBAO_ASR_2_RESOURCE = "volc.seedasr.sauc.duration"  # Recommended

DOUBAO_ASR_ERROR_CODES = {
    20000000: "Success",
    45000001: "Invalid request parameters",
    45000002: "Empty audio payload",
    45000081: "Timeout waiting for audio",
    45000151: "Incorrect audio format",
    55000031: "Server busy/overloaded",
}

def _build_header(msg_type: int, flags: int, serialization: int, compression: int) -> bytes:
    """Builds the 4-byte header for OpenSpeech protocol."""
    # Byte 0: [protocol_version(4bit) | header_size(4bit)] = 0x11
    byte0 = (1 << 4) | 1  # version 1, header_size 1 (which means 4 bytes)
    # Byte 1: [message_type(4bit) | type_specific_flags(4bit)]
    byte1 = (msg_type << 4) | flags
    # Byte 2: [serialization(4bit) | compression(4bit)]
    byte2 = (serialization << 4) | compression
    # Byte 3: reserved
    byte3 = 0x00
    return struct.pack("!BBBB", byte0, byte1, byte2, byte3)

def _build_full_client_request(payload: dict) -> bytes:
    """Builds the initial configuration request packet."""
    payload_bytes = json.dumps(payload).encode("utf-8")
    compressed = gzip.compress(payload_bytes)
    
    header = _build_header(
        msg_type=1,      # full client request
        flags=0,         # no sequence
        serialization=1, # JSON
        compression=1,   # gzip
    )
    
    payload_size = struct.pack("!I", len(compressed))
    return header + payload_size + compressed

def _build_audio_request(audio_data: bytes, is_last: bool = False) -> bytes:
    """Builds an audio chunk request packet."""
    compressed = gzip.compress(audio_data)
    
    flags = 2 if is_last else 0 # 2 = last packet (no seq), 0 = no sequence
    
    header = _build_header(
        msg_type=2,      # audio-only
        flags=flags,     
        serialization=0, # none
        compression=1,   # gzip
    )
    
    payload_size = struct.pack("!I", len(compressed))
    return header + payload_size + compressed

def _parse_server_response(data: bytes) -> dict:
    """Parses a normal server response."""
    if len(data) < 4:
        raise ValueError("Response too short")
    
    header = data[:4]
    byte0, byte1, byte2, byte3 = struct.unpack("!BBBB", header)
    
    msg_type = (byte1 >> 4) & 0x0F
    
    if msg_type != 9:
        raise ValueError(f"Not a server response, msg_type: {msg_type}")
    
    flags = byte1 & 0x0F
    has_seq = flags in (1, 3)
    
    compression = byte2 & 0x0F
    serialization = (byte2 >> 4) & 0x0F
    
    offset = 4
    if has_seq:
        offset += 4  # Skip sequence number
        
    payload_size = struct.unpack("!I", data[offset:offset+4])[0]
    offset += 4
    
    payload_data = data[offset:offset+payload_size]
    
    if compression == 1:
        payload_data = gzip.decompress(payload_data)
        
    if serialization == 1:
        return json.loads(payload_data.decode("utf-8"))
    
    return {"raw": payload_data}

def _parse_server_error(data: bytes) -> tuple[int, str]:
    """Parses a server error response.

    Error frame layout (per OpenSpeech docs):
      [Header: 4B] + [Error Code: 4B uint32] + [Msg Size: 4B uint32] + [Msg: UTF-8]
    """
    if len(data) < 12:
        return -1, "Error response too short to parse"

    offset = 4  # Skip 4-byte header
    error_code = struct.unpack("!I", data[offset:offset + 4])[0]
    offset += 4
    msg_size = struct.unpack("!I", data[offset:offset + 4])[0]
    offset += 4
    error_msg = data[offset:offset + msg_size].decode("utf-8", errors="replace")
    return error_code, error_msg

async def doubao_asr_transcribe_file(
    file_path: Path | str,
    api_key: str,
    resource_id: str = DOUBAO_ASR_2_RESOURCE,
) -> dict:
    """
    Transcribe a local audio file using ByteDance Volcengine Doubao ASR.
    
    Args:
        file_path: Path to the audio file
        api_key: The authentication API key
        resource_id: Resource ID for the Doubao ASR model
        
    Returns:
        dict: A dictionary containing transcribed text, duration, and word timestamps.
    """
    if websockets is None:
        raise ImportError("websockets library is required for doubao_asr_transcribe_file")
        
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
        
    ext = file_path.suffix.lower().strip(".")
    fmt = "mp3"
    if ext in ["wav", "pcm", "ogg", "mp3"]:
        fmt = ext
        
    headers = {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Sequence": "-1",
        "X-Api-Connect-Id": str(uuid.uuid4()),
    }
    
    payload = {
        "user": {"uid": "voicespirit_user"},
        "audio": {
            "format": fmt,
            "codec": "raw",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": False,
            "show_utterances": True,
            "result_type": "full",
        },
    }
    
    final_text = ""
    words = []
    duration = None
    
    async with websockets.connect(DOUBAO_ASR_NOSTREAM_URL, extra_headers=headers) as ws:
        # 1. Send full client request
        req_bytes = _build_full_client_request(payload)
        await ws.send(req_bytes)
        
        # 2. Read file and send audio chunks
        chunk_size = 3200
        sent_last = False
        with open(file_path, "rb") as f:
            while True:
                data = f.read(chunk_size)
                if not data:
                    # EOF reached — send an empty last-packet marker if we
                    # haven't already (happens when file size is an exact
                    # multiple of chunk_size).
                    if not sent_last:
                        await ws.send(_build_audio_request(b"", is_last=True))
                        sent_last = True
                    break
                is_last = len(data) < chunk_size
                await ws.send(_build_audio_request(data, is_last=is_last))
                if is_last:
                    sent_last = True
                    break
                
        # 3. Receive server responses
        try:
            async with asyncio.timeout(120):
                while True:
                    msg = await ws.recv()
                    
                    if isinstance(msg, bytes):
                        byte1 = msg[1]
                        msg_type = (byte1 >> 4) & 0x0F
                        
                        if msg_type == 15: # Server error
                            code, err_msg = _parse_server_error(msg)
                            desc = DOUBAO_ASR_ERROR_CODES.get(code, "Unknown Error")
                            raise Exception(f"Doubao ASR Error {code}: {desc} - {err_msg}")
                            
                        elif msg_type == 9: # Server response
                            resp_json = _parse_server_response(msg)
                            
                            if "utterances" in resp_json:
                                for utt in resp_json["utterances"]:
                                    if "words" in utt:
                                        for w in utt["words"]:
                                            words.append({
                                                "text": w["text"],
                                                "start": w.get("start_time", 0) / 1000.0,
                                                "end": w.get("end_time", 0) / 1000.0,
                                            })
                            if "text" in resp_json:
                                final_text = resp_json["text"]
                                
                            if "duration" in resp_json:
                                duration = resp_json["duration"] / 1000.0
                                
                            flags = byte1 & 0x0F
                            if flags in (2, 3): # Last packet
                                break
                                
        except asyncio.TimeoutError:
            raise TimeoutError("Timeout waiting for Doubao ASR response")
            
    return {
        "text": final_text,
        "duration_seconds": duration,
        "words": words if words else None
    }
