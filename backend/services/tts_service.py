from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import html
import json
import os
import re
import sys
import threading
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from .config_loader import BackendConfig, get_data_dir
from .script_parser import parse_script_with_fallback
from .doubao_tts_provider import (
    DOUBAO_VOICES,
    DEFAULT_DOUBAO_TTS_VOICE,
    DEFAULT_DOUBAO_TTS_CLUSTER,
    doubao_tts_synthesize,
    is_doubao_voice,
)

try:
    import edge_tts
except ImportError:
    edge_tts = None

# edge_tts.Communicate.save() has no built-in timeout: a stalled Microsoft
# endpoint would hang the synthesis coroutine forever (the realtime
# synthesize_tts tool path included). Generous enough for long PDF read-aloud.
EDGE_TTS_TIMEOUT_SECONDS = 180.0

# Dedicated executor for blocking TTS work (local ChatTTS/torch inference, the
# dashscope SDK's synchronous call(), Azure pull-stream reads). Keeps these
# potentially minutes-long jobs off asyncio's default pool so they cannot
# starve unrelated to_thread users mid-request (mirrors _RECORDER_DB_EXECUTOR).
_TTS_BLOCKING_EXECUTOR = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="tts-blocking"
)


async def _run_tts_blocking(func: Any, *args: Any) -> Any:
    """Run a blocking TTS call on the dedicated TTS executor."""
    loop = asyncio.get_running_loop()
    if args:
        return await loop.run_in_executor(
            _TTS_BLOCKING_EXECUTOR, functools.partial(func, *args)
        )
    return await loop.run_in_executor(_TTS_BLOCKING_EXECUTOR, func)

try:
    import azure.cognitiveservices.speech as speechsdk
except ImportError:
    speechsdk = None


TTS_ENGINE_EDGE = "edge"
TTS_ENGINE_QWEN_FLASH = "qwen_flash"
TTS_ENGINE_MINIMAX = "minimax"
TTS_ENGINE_XIAOMI = "xiaomi"
TTS_ENGINE_OPENAI = "openai"
TTS_ENGINE_ELEVENLABS = "elevenlabs"
TTS_ENGINE_CHATTTS = "chattts"
TTS_ENGINE_GPT_SOVITS = "gpt_sovits"
TTS_ENGINE_AZURE = "azure"
TTS_ENGINE_DOUBAO = "doubao"

SUPPORTED_TTS_ENGINES = {
    TTS_ENGINE_EDGE,
    TTS_ENGINE_QWEN_FLASH,
    TTS_ENGINE_MINIMAX,
    TTS_ENGINE_XIAOMI,
    TTS_ENGINE_OPENAI,
    TTS_ENGINE_ELEVENLABS,
    TTS_ENGINE_CHATTTS,
    TTS_ENGINE_GPT_SOVITS,
    TTS_ENGINE_AZURE,
    TTS_ENGINE_DOUBAO,
}

OPENAI_VOICES = [
    {"name": "alloy", "short_name": "Alloy", "locale": "multi", "gender": "Neutral"},
    {"name": "echo", "short_name": "Echo", "locale": "multi", "gender": "Male"},
    {"name": "fable", "short_name": "Fable", "locale": "multi", "gender": "Neutral"},
    {"name": "onyx", "short_name": "Onyx", "locale": "multi", "gender": "Male"},
    {"name": "nova", "short_name": "Nova", "locale": "multi", "gender": "Female"},
    {"name": "shimmer", "short_name": "Shimmer", "locale": "multi", "gender": "Female"},
]

ELEVENLABS_VOICES = [
    {"name": "21m0aEP3W9qOfdrWSyXx", "short_name": "Rachel", "locale": "en-US", "gender": "Female"},
    {"name": "2Ezo5yI4SP56xRC3pOI3", "short_name": "Clyde", "locale": "en-US", "gender": "Male"},
    {"name": "AZnzlk1XvdvUeBnXmlld", "short_name": "Dom", "locale": "en-US", "gender": "Male"},
    {"name": "CYw3db4g4HsRz56a4v7t", "short_name": "Dave", "locale": "en-GB", "gender": "Male"},
    {"name": "ErXwobaYiN019PkySvjV", "short_name": "Antoni", "locale": "en-US", "gender": "Male"},
    {"name": "Lcfc5NaZ2c0U3L90tI6C", "short_name": "Emily", "locale": "en-US", "gender": "Female"},
    {"name": "pNInz6obpgqAjEL4s7P5", "short_name": "Adam", "locale": "en-US", "gender": "Male"},
    {"name": "pi50t7uMc9ZUB5L7vew", "short_name": "Nicole", "locale": "en-US", "gender": "Female"},
    {"name": "EXAVITQu4vr4xnSDxMaL", "short_name": "Bella", "locale": "en-US", "gender": "Female"},
]

DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_EDGE_EN_VOICE = "en-US-AvaNeural"
DEFAULT_QWEN_FLASH_MODEL = "qwen3-tts-flash-2025-11-27"
DEFAULT_MINIMAX_MODEL = "speech-02-turbo"
DEFAULT_MINIMAX_URL = "https://api.minimax.chat/v1/t2a_v2"
DEFAULT_XIAOMI_MODEL = "mimo-v2.5-tts"
DEFAULT_XIAOMI_URL = "https://api.xiaomimimo.com"
MEDIA_TYPE_MP3 = "audio/mpeg"
MEDIA_TYPE_WAV = "audio/wav"
GPT_SOVITS_VOICE_PREFIX = "gpt_sovits_"
LOCAL_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".webm", ".mp4"}
LOCAL_AUDIO_EXTENSION_BY_MIME = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
}

FALLBACK_EDGE_VOICES = [
    {"name": "zh-CN-XiaoxiaoNeural", "short_name": "Xiaoxiao", "locale": "zh-CN", "gender": "Female"},
    {"name": "zh-CN-YunxiNeural", "short_name": "Yunxi", "locale": "zh-CN", "gender": "Male"},
    {"name": "en-US-JennyNeural", "short_name": "Jenny", "locale": "en-US", "gender": "Female"},
    {"name": "en-US-GuyNeural", "short_name": "Guy", "locale": "en-US", "gender": "Male"},
]

QWEN_FLASH_VOICES = [
    {"name": "Cherry", "short_name": "芊悦 (Cherry)", "locale": "zh-CN", "gender": "Female"},
    {"name": "Serena", "short_name": "苏瑶 (Serena)", "locale": "zh-CN", "gender": "Female"},
    {"name": "Ethan", "short_name": "晨煦 (Ethan)", "locale": "zh-CN", "gender": "Male"},
    {"name": "Bella", "short_name": "萌宝 (Bella)", "locale": "zh-CN", "gender": "Female"},
    {"name": "Ryan", "short_name": "甜茶 (Ryan)", "locale": "zh-CN", "gender": "Male"},
    {"name": "Mia", "short_name": "乖小妹 (Mia)", "locale": "zh-CN", "gender": "Female"},
    {"name": "Moon", "short_name": "月白 (Moon)", "locale": "zh-CN", "gender": "Male"},
    {"name": "Ono Anna", "short_name": "小野杏 (Ono Anna)", "locale": "ja-JP", "gender": "Female"},
    {"name": "Sohee", "short_name": "素熙 (Sohee)", "locale": "ko-KR", "gender": "Female"},
    {"name": "Andre", "short_name": "安德雷 (Andre)", "locale": "multi", "gender": "Male"},
]

# Qwen-Audio-TTS system voices (qwen-audio-3.0-tts-flash / qwen-audio-3.0-tts-plus).
# These use the "longan v3.6" voice family per the official Qwen-Audio-TTS voice list
# (https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list) and are NOT
# interchangeable with the qwen3-tts-flash voices above (Cherry/Ono Anna/...).
QWEN_AUDIO_TTS_VOICES = [
    {"name": "longanhuan_v3.6", "short_name": "龙安欢 (longanhuan_v3.6)", "locale": "zh-CN", "gender": "Female"},
    {"name": "longanfengyue", "short_name": "龙安风悦 (longanfengyue)", "locale": "zh-CN", "gender": "Female"},
    {"name": "longanyuanfei", "short_name": "龙安元妃 (longanyuanfei)", "locale": "zh-CN", "gender": "Female"},
    {"name": "longanlingxi", "short_name": "龙安灵希 (longanlingxi)", "locale": "zh-CN", "gender": "Female"},
    {"name": "longanxiaoxin", "short_name": "龙安小昕 (longanxiaoxin)", "locale": "zh-CN", "gender": "Female"},
    {"name": "longjielidou_v3.6", "short_name": "龙杰力豆 (longjielidou_v3.6)", "locale": "zh-CN", "gender": "Male"},
    {"name": "longpaopao_v3.6", "short_name": "龙泡泡 (longpaopao_v3.6)", "locale": "zh-CN", "gender": "Neutral"},
    {"name": "longhuohuo_v3.6", "short_name": "龙火火 (longhuohuo_v3.6)", "locale": "zh-CN", "gender": "Male"},
    {"name": "longchuanshu_v3.6", "short_name": "龙川叔 (longchuanshu_v3.6)", "locale": "zh-CN", "gender": "Male"},
    {"name": "loongmary", "short_name": "Loong Mary (loongmary)", "locale": "en-GB", "gender": "Female"},
    {"name": "loongeva_v3.6", "short_name": "Loong Eva (loongeva_v3.6)", "locale": "en-US", "gender": "Female"},
    {"name": "loongjohn", "short_name": "Loong John (loongjohn)", "locale": "en-US", "gender": "Male"},
]

DEFAULT_QWEN_AUDIO_TTS_VOICE = "longanhuan_v3.6"


def is_qwen_audio_tts_model(model: str | None) -> bool:
    """True for the Qwen-Audio-TTS family (qwen-audio-3.0-tts-flash/plus).

    These models use the longan voice family, unlike qwen3-tts-* models which
    use the Cherry/Ono Anna voice family.
    """
    normalized = str(model or "").strip().lower()
    return normalized.startswith("qwen-audio-") and "-tts-" in normalized


MINIMAX_VOICES = [
    {"name": "female-shaonv", "short_name": "少女音色", "locale": "zh-CN", "gender": "Female"},
    {"name": "female-yujie", "short_name": "御姐音色", "locale": "zh-CN", "gender": "Female"},
    {"name": "male-qn-jingying", "short_name": "精英青年音色", "locale": "zh-CN", "gender": "Male"},
    {"name": "male-qn-badao", "short_name": "霸道青年音色", "locale": "zh-CN", "gender": "Male"},
    {"name": "female-tianmei", "short_name": "甜美女性音色", "locale": "zh-CN", "gender": "Female"},
    {"name": "clever_boy", "short_name": "聪明男童", "locale": "zh-CN", "gender": "Male"},
    {"name": "English_Graceful_Lady", "short_name": "Graceful Lady", "locale": "en-US", "gender": "Female"},
    {"name": "English_Trustworthy_Man", "short_name": "Trustworthy Man", "locale": "en-US", "gender": "Male"},
    {"name": "Japanese_GracefulMaiden", "short_name": "Graceful Maiden", "locale": "ja-JP", "gender": "Female"},
    {"name": "Korean_CalmLady", "short_name": "Calm Lady", "locale": "ko-KR", "gender": "Female"},
]

XIAOMI_VOICES = [
    {"name": "mimo_default", "short_name": "小米默认 (mimo_default)", "locale": "zh-CN", "gender": "Female"},
    {"name": "茉莉", "short_name": "茉莉 (Moli)", "locale": "zh-CN", "gender": "Female"},
    {"name": "冰糖", "short_name": "冰糖 (Bingtang)", "locale": "zh-CN", "gender": "Female"},
    {"name": "苏打", "short_name": "苏打 (Soda)", "locale": "zh-CN", "gender": "Male"},
    {"name": "白桦", "short_name": "白桦 (Baihua)", "locale": "zh-CN", "gender": "Male"},
    {"name": "Mia", "short_name": "Mia (Mia)", "locale": "en-US", "gender": "Female"},
    {"name": "Chloe", "short_name": "Chloe (Chloe)", "locale": "en-US", "gender": "Female"},
    {"name": "Milo", "short_name": "Milo (Milo)", "locale": "en-US", "gender": "Male"},
]

CHATTTS_VOICES = [
    {"name": "2", "short_name": "默认男声 (Seed 2)", "locale": "zh-CN", "gender": "Male"},
    {"name": "2422", "short_name": "自然男声 (Seed 2422)", "locale": "zh-CN", "gender": "Male"},
    {"name": "88", "short_name": "清澈女声 (Seed 88)", "locale": "zh-CN", "gender": "Female"},
    {"name": "111", "short_name": "活泼女声 (Seed 111)", "locale": "zh-CN", "gender": "Female"},
    {"name": "custom", "short_name": "自定义 Seed...", "locale": "zh-CN", "gender": "Neutral"},
]

GPT_SOVITS_VOICES = [
    {"name": "default", "short_name": "默认 API 角色 (Default)", "locale": "zh-CN", "gender": "Neutral"},
]


_global_chattts_instance = None
_global_chattts_lock = threading.Lock()


@dataclass(frozen=True)
class TTSAudioResult:
    file_path: str
    voice: str
    engine: str
    media_type: str
    filename: str
    cache_hit: bool

    def __iter__(self):
        # Backward compatible with older callers that unpacked
        # (file_path, used_voice, cache_hit).
        yield self.file_path
        yield self.voice
        yield self.cache_hit


class TTSService:
    def __init__(
        self,
        output_dir: Path | None = None,
        config: BackendConfig | None = None,
    ):
        self.config = config or BackendConfig()
        root = Path(__file__).resolve().parents[1]
        resolved_output = output_dir or (root / "temp_audio")
        self.output_dir = resolved_output
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_old_cache()

    def _cleanup_old_cache(self, max_files: int = 500, max_age_hours: int = 72) -> None:
        """Remove stale TTS audio files to prevent unbounded disk usage."""
        import time
        try:
            files = sorted(
                (f for f in self.output_dir.iterdir() if f.is_file() and f.suffix in {".mp3", ".wav", ".ogg", ".opus"}),
                key=lambda f: f.stat().st_mtime,
            )
        except OSError:
            return
        now = time.time()
        cutoff = now - max_age_hours * 3600
        # Remove files older than cutoff
        for f in files:
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            except OSError:
                continue
        # If still over limit, remove oldest first
        remaining = sorted(
            (f for f in self.output_dir.iterdir() if f.is_file() and f.suffix in {".mp3", ".wav", ".ogg", ".opus"}),
            key=lambda f: f.stat().st_mtime,
        )
        if len(remaining) > max_files:
            for f in remaining[:len(remaining) - max_files]:
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    continue

    @staticmethod
    def _atomic_write_bytes(path: Path, data: bytes) -> None:
        """Write *data* to *path* atomically (tmp file + os.replace)."""
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        closed = False
        try:
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.close(fd)
            closed = True
            os.replace(tmp, str(path))
        except BaseException:
            if not closed:
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def _legacy_gpt_sovits_voices_dir(self) -> Path:
        return Path(__file__).resolve().parents[1] / "data" / "gpt_sovits_voices"

    def get_gpt_sovits_voices_dir(self) -> Path:
        return get_data_dir() / "gpt_sovits_voices"

    def _gpt_sovits_voice_dirs(self) -> list[Path]:
        primary = self.get_gpt_sovits_voices_dir()
        legacy = self._legacy_gpt_sovits_voices_dir()
        return [primary] if primary == legacy else [primary, legacy]

    @staticmethod
    def normalize_local_voice_name(name: str) -> str:
        raw = str(name or "").strip()
        if not raw:
            raise ValueError("Voice name is required.")
        normalized = re.sub(r"\s+", "_", raw)
        normalized = re.sub(r"[^\w.-]+", "_", normalized, flags=re.UNICODE)
        normalized = normalized.strip("._-")
        if not normalized:
            digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
            normalized = f"voice_{digest}"
        if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
            raise ValueError("Voice name contains invalid path characters.")
        if len(normalized) > 80:
            digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:8]
            normalized = f"{normalized[:71]}_{digest}"
        return normalized

    @classmethod
    def _parse_local_gpt_sovits_voice_name(cls, voice_name: str) -> str:
        clone_name = str(voice_name or "").strip()
        if clone_name.startswith(GPT_SOVITS_VOICE_PREFIX):
            clone_name = clone_name[len(GPT_SOVITS_VOICE_PREFIX):]
        normalized = cls.normalize_local_voice_name(clone_name)
        if normalized != clone_name:
            raise ValueError("Invalid GPT-SoVITS voice name.")
        return normalized

    @staticmethod
    def _infer_local_audio_extension(
        filename: str | None,
        content_type: str | None,
        data: bytes,
    ) -> str:
        suffix = Path(filename or "").suffix.lower()
        if suffix in LOCAL_AUDIO_EXTENSIONS:
            return suffix

        mime_extension = LOCAL_AUDIO_EXTENSION_BY_MIME.get(str(content_type or "").split(";")[0].strip().lower())
        if mime_extension:
            return mime_extension

        if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
            return ".wav"
        if data.startswith(b"ID3") or data[:2] in {b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"}:
            return ".mp3"
        if data.startswith(b"fLaC"):
            return ".flac"
        if data.startswith(b"OggS"):
            return ".ogg"
        if data.startswith(b"\x1a\x45\xdf\xa3"):
            return ".webm"
        if len(data) > 12 and data[4:8] == b"ftyp":
            return ".m4a"

        raise ValueError("Unsupported audio file format for GPT-SoVITS clone.")

    def _iter_local_gpt_sovits_audio_files(self) -> list[Path]:
        files: dict[str, Path] = {}
        for voices_dir in self._gpt_sovits_voice_dirs():
            if not voices_dir.exists():
                continue
            for file in sorted(voices_dir.iterdir()):
                if file.is_file() and file.suffix.lower() in LOCAL_AUDIO_EXTENSIONS:
                    files.setdefault(file.stem, file)
        return list(files.values())

    def _find_local_gpt_sovits_voice(self, clone_name: str) -> tuple[Path, Path | None] | None:
        normalized = self._parse_local_gpt_sovits_voice_name(clone_name)
        for voices_dir in self._gpt_sovits_voice_dirs():
            if not voices_dir.exists():
                continue
            for extension in sorted(LOCAL_AUDIO_EXTENSIONS):
                audio_file = voices_dir / f"{normalized}{extension}"
                if audio_file.exists() and audio_file.is_file():
                    text_file = voices_dir / f"{normalized}.txt"
                    return audio_file, text_file if text_file.exists() else None
        return None

    def save_local_gpt_sovits_voice(
        self,
        *,
        preferred_name: str,
        audio_bytes: bytes,
        filename: str | None,
        content_type: str | None,
        prompt_text: str,
    ) -> dict[str, Any]:
        clone_name = self.normalize_local_voice_name(preferred_name)
        extension = self._infer_local_audio_extension(filename, content_type, audio_bytes)
        voices_dir = self.get_gpt_sovits_voices_dir()
        voices_dir.mkdir(parents=True, exist_ok=True)

        for old_file in voices_dir.glob(f"{clone_name}.*"):
            if old_file.suffix.lower() in LOCAL_AUDIO_EXTENSIONS or old_file.suffix.lower() == ".txt":
                old_file.unlink()

        audio_path = voices_dir / f"{clone_name}{extension}"
        self._atomic_write_bytes(audio_path, audio_bytes)
        text_path = voices_dir / f"{clone_name}.txt"
        text_path.write_text(prompt_text.strip(), encoding="utf-8")

        return {
            "voice": f"{GPT_SOVITS_VOICE_PREFIX}{clone_name}",
            "type": "voice_clone",
            "target_model": "gpt-sovits-local",
            "preferred_name": clone_name,
            "provider": "gpt_sovits",
        }

    def delete_local_gpt_sovits_voice(self, voice_name: str) -> bool:
        clone_name = self._parse_local_gpt_sovits_voice_name(voice_name)
        deleted = False
        for voices_dir in self._gpt_sovits_voice_dirs():
            if not voices_dir.exists():
                continue
            for extension in sorted(LOCAL_AUDIO_EXTENSIONS | {".txt"}):
                candidate = voices_dir / f"{clone_name}{extension}"
                if candidate.exists() and candidate.is_file():
                    candidate.unlink()
                    deleted = True
        return deleted

    def _get_local_gpt_sovits_voices(self) -> list[dict[str, Any]]:
        voices = []
        for file in self._iter_local_gpt_sovits_audio_files():
            name = file.stem
            voices.append({
                "name": f"{GPT_SOVITS_VOICE_PREFIX}{name}",
                "short_name": f"{name} (本地克隆)",
                "locale": "multi",
                "gender": "Clone",
                "audio_format": file.suffix.lower().lstrip("."),
            })
        return voices

    def _clean_text(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", cleaned)
        cleaned = cleaned.strip()
        if not cleaned:
            raise ValueError("Text is empty after cleanup.")
        if len(cleaned) > 3000:
            raise ValueError("Text is too long. Maximum length is 3000 characters.")
        return cleaned

    def _normalize_engine(self, engine: str | None) -> str:
        candidate = str(engine or TTS_ENGINE_EDGE).strip().lower()
        if candidate not in SUPPORTED_TTS_ENGINES:
            raise ValueError(f"Unsupported TTS engine: {candidate}")
        return candidate

    def _detect_edge_voice(self, text: str) -> str:
        if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
            return "ja-JP-NanamiNeural"
        if re.search(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", text):
            return "ko-KR-SunHiNeural"
        if re.search(r"[\u0400-\u04ff]", text):
            return "ru-RU-SvetlanaNeural"
        if re.search(r"[\u4e00-\u9fff]", text):
            return DEFAULT_EDGE_VOICE
        if re.search(r"[äöüßÄÖÜ]", text):
            return "de-DE-KatjaNeural"
        if re.search(r"[œæçàéèêëîïôùûüÿÀÉÈÊËÎÏÔÙÛÜŸ]", text):
            return "fr-FR-DeniseNeural"
        if re.search(r"[ñ¿¡ÁÉÍÓÚáéíóú]", text):
            return "es-ES-ElviraNeural"
        if re.search(r"[a-zA-Z]", text):
            return DEFAULT_EDGE_EN_VOICE
        return DEFAULT_EDGE_VOICE

    def _resolve_edge_voice_for_text(self, text: str, voice: str) -> str:
        voice_lower = voice.lower()

        if re.search(r"[\u3040-\u309f\u30a0-\u30ff]", text):
            if not ("ja-jp" in voice_lower or "ja" in voice_lower):
                return "ja-JP-NanamiNeural"
        elif re.search(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]", text):
            if not ("ko-kr" in voice_lower or "ko" in voice_lower):
                return "ko-KR-SunHiNeural"
        elif re.search(r"[\u0400-\u04ff]", text):
            if not ("ru-ru" in voice_lower or "ru" in voice_lower):
                return "ru-RU-SvetlanaNeural"
        elif re.search(r"[\u4e00-\u9fff]", text):
            if not ("zh-cn" in voice_lower or "zh-tw" in voice_lower or "zh-hk" in voice_lower or "zh" in voice_lower):
                return DEFAULT_EDGE_VOICE
        elif re.search(r"[äöüßÄÖÜ]", text):
            if not ("de-de" in voice_lower or "de" in voice_lower):
                return "de-DE-KatjaNeural"
        elif re.search(r"[œæçàéèêëîïôùûüÿÀÉÈÊËÎÏÔÙÛÜŸ]", text):
            if not ("fr-fr" in voice_lower or "fr" in voice_lower):
                return "fr-FR-DeniseNeural"
        elif re.search(r"[ñ¿¡ÁÉÍÓÚáéíóú]", text):
            if not ("es-es" in voice_lower or "es" in voice_lower):
                return "es-ES-ElviraNeural"
        elif re.search(r"[a-zA-Z]", text):
            if not ("en-us" in voice_lower or "en-gb" in voice_lower or "en-au" in voice_lower or "en-ca" in voice_lower or "en" in voice_lower):
                return DEFAULT_EDGE_EN_VOICE

        return voice

    def _audio_profile_for_engine(self, engine: str) -> tuple[str, str]:
        if engine in {TTS_ENGINE_CHATTTS, TTS_ENGINE_GPT_SOVITS}:
            return "wav", MEDIA_TYPE_WAV
        return "mp3", MEDIA_TYPE_MP3

    def _make_filename(self, text: str, voice: str, rate: str, engine: str, extension: str, model: str | None = None) -> str:
        digest = hashlib.md5(f"{engine}|{model or ''}|{voice}|{rate}|{text}".encode("utf-8")).hexdigest()[:16]
        return f"{engine}_{digest}.{extension}"

    def _filter_by_locale(self, voices: list[dict[str, Any]], locale: str | None) -> list[dict[str, Any]]:
        if not locale:
            return voices
        return [voice for voice in voices if str(voice.get("locale", "")).startswith(locale)]

    def _dashscope_key(self) -> str:
        return self.config.get_provider_settings("DashScope").get("api_key", "").strip()

    def _minimax_settings(self) -> tuple[str, str]:
        self.config.reload()
        settings = self.config.get_all().get("minimax", {})
        api_key = str(settings.get("api_key", "")).strip()
        base_url = str(settings.get("api_url", "")).strip()
        if not base_url:
            base_url = str(self.config.get_all().get("api_urls", {}).get("MiniMax", "")).strip()
        if not base_url:
            base_url = DEFAULT_MINIMAX_URL
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        return api_key, base_url

    def _xiaomi_settings(self) -> tuple[str, str]:
        self.config.reload()
        settings = self.config.get_all().get("xiaomi", {})
        api_key = str(settings.get("api_key", "")).strip()
        base_url = str(settings.get("api_url", "")).strip()
        if not base_url:
            base_url = str(self.config.get_all().get("api_urls", {}).get("Xiaomi", "")).strip()
        if not base_url:
            base_url = DEFAULT_XIAOMI_URL
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        return api_key, base_url

    def _gpt_sovits_settings(self) -> tuple[str, str]:
        self.config.reload()
        gpt_sovits_config = self.config.get_all().get("api_urls", {})
        base_url = str(gpt_sovits_config.get("GPT-SoVITS", "")).strip()
        if not base_url:
            base_url = "http://127.0.0.1:9880"
        
        api_keys = self.config.get_all().get("api_keys", {})
        api_key = str(api_keys.get("gpt_sovits_api_key", "")).strip()
        
        if not base_url.startswith(("http://", "https://")):
            base_url = f"http://{base_url}"
        return api_key, base_url

    def _doubao_settings(self) -> tuple[str, str, str]:
        """Return (access_token, app_id, cluster) for Doubao OpenSpeech TTS."""
        self.config.reload()
        access_token = str(self.config.get_setting("doubao_access_token", "")).strip()
        if not access_token:
            # Fallback to doubao_api_key for backward compatibility
            access_token = str(self.config.get_setting("doubao_api_key", "")).strip()
        app_id = str(self.config.get_setting("doubao_app_id", "")).strip()
        cfg = self.config.get_all()
        cluster = str(cfg.get("doubao", {}).get("tts_cluster", "")).strip() or DEFAULT_DOUBAO_TTS_CLUSTER
        return access_token, app_id, cluster

    def _chattts_runtime_settings(self) -> tuple[Path, str, str]:
        self.config.reload()
        tts_settings = self.config.get_all().get("tts_settings", {})
        model_dir = str(
            tts_settings.get("chattts_model_dir")
            or os.environ.get("VOICESPIRIT_CHATTTS_MODEL_DIR", "")
        ).strip()
        if not model_dir:
            model_dir = str(Path.home() / ".cache" / "modelscope" / "hub" / "pzc163" / "ChatTTS")

        hf_endpoint = str(
            tts_settings.get("chattts_hf_endpoint")
            or os.environ.get("VOICESPIRIT_CHATTTS_HF_ENDPOINT", "")
        ).strip()
        device = str(
            tts_settings.get("chattts_device")
            or os.environ.get("VOICESPIRIT_CHATTTS_DEVICE", "auto")
        ).strip().lower() or "auto"
        return Path(model_dir).expanduser(), hf_endpoint, device

    async def _generate_chattts_audio(self, text: str, voice: str, path: Path) -> None:
        await _run_tts_blocking(self._generate_chattts_audio_sync, text, voice, path)

    def _generate_chattts_audio_sync(self, text: str, voice: str, path: Path) -> None:
        global _global_chattts_instance
        try:
            import ChatTTS
            import torch
            import soundfile as sf
        except ImportError as exc:
            raise RuntimeError(
                "ChatTTS local engine dependencies are missing. Install ChatTTS, torch, and soundfile."
            ) from exc

        model_dir, hf_endpoint, device_setting = self._chattts_runtime_settings()
        if hf_endpoint:
            os.environ["HF_ENDPOINT"] = hf_endpoint

        with _global_chattts_lock:
            if _global_chattts_instance is None:
                if not model_dir.exists():
                    raise RuntimeError(
                        f"ChatTTS model directory not found at {model_dir}. "
                        "Set tts_settings.chattts_model_dir or VOICESPIRIT_CHATTTS_MODEL_DIR."
                    )

                device = device_setting
                if device == "auto":
                    device = "cuda" if torch.cuda.is_available() else "cpu"

                _global_chattts_instance = ChatTTS.Chat()
                _global_chattts_instance.load_models(
                    vocos_config_path=str(model_dir / "config" / "vocos.yaml"),
                    vocos_ckpt_path=str(model_dir / "asset" / "Vocos.pt"),
                    dvae_config_path=str(model_dir / "config" / "dvae.yaml"),
                    dvae_ckpt_path=str(model_dir / "asset" / "DVAE.pt"),
                    gpt_config_path=str(model_dir / "config" / "gpt.yaml"),
                    gpt_ckpt_path=str(model_dir / "asset" / "GPT.pt"),
                    decoder_config_path=str(model_dir / "config" / "decoder.yaml"),
                    decoder_ckpt_path=str(model_dir / "asset" / "Decoder.pt"),
                    tokenizer_path=str(model_dir / "asset" / "tokenizer.pt"),
                    device=device,
                )

            seed = 2
            try:
                if voice and voice.isdigit():
                    seed = int(voice)
                elif voice and voice.startswith("seed_"):
                    seed = int(voice.split("_")[-1])
            except Exception:
                pass

            spk_stat_path = model_dir / "asset" / "spk_stat.pt"
            if spk_stat_path.exists():
                std, mean = torch.load(str(spk_stat_path), map_location="cpu").chunk(2)
                generator = torch.Generator(device="cpu")
                generator.manual_seed(seed)
                spk_emb = torch.randn(768, generator=generator) * std + mean
                params_infer_code = {"spk_emb": spk_emb}
            else:
                params_infer_code = {}

            wavs = _global_chattts_instance.infer(
                [text],
                params_infer_code=params_infer_code,
                params_refine_text={"prompt": "[oral_2][laugh_0][break_6]"},
            )
            wav = wavs[0]
            if wav.ndim > 1 and wav.shape[0] == 1:
                wav = wav[0]

            import tempfile as _tf
            _fd, _tmp = _tf.mkstemp(dir=str(path.parent), suffix=".tmp")
            os.close(_fd)
            try:
                sf.write(_tmp, wav.T if wav.ndim > 1 else wav, 24000)
                os.replace(_tmp, str(path))
            except BaseException:
                try:
                    os.unlink(_tmp)
                except OSError:
                    pass
                raise

    async def _generate_gpt_sovits_audio(self, text: str, voice: str, path: Path) -> None:
        api_key, base_url = self._gpt_sovits_settings()
        
        ref_audio_path = ""
        prompt_text = ""
        prompt_lang = ""
        
        if voice and voice.startswith(GPT_SOVITS_VOICE_PREFIX):
            clone_name = voice[len(GPT_SOVITS_VOICE_PREFIX):]
            local_voice = self._find_local_gpt_sovits_voice(clone_name)
            if local_voice:
                audio_file, text_file = local_voice
                ref_audio_path = str(audio_file.absolute())
                if text_file:
                    try:
                        prompt_text = text_file.read_text(encoding="utf-8").strip()
                    except Exception:
                        pass

                prompt_lang = "zh"
                if any("\u4e00" <= c <= "\u9fff" for c in prompt_text):
                    prompt_lang = "zh"
                elif prompt_text and all(ord(c) < 128 for c in prompt_text):
                    prompt_lang = "en"
        
        text_lang = "auto"
        if any(ord(c) > 0x4e00 and ord(c) < 0x9fff for c in text):
            text_lang = "zh"
        elif all(ord(c) < 128 for c in text):
            text_lang = "en"

        payload = {
            "text": text,
            "text_lang": text_lang,
        }
        if ref_audio_path:
            payload["ref_audio_path"] = ref_audio_path
            payload["prompt_text"] = prompt_text
            payload["prompt_lang"] = prompt_lang

        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                response = await client.post(base_url, json=payload, headers=headers)
                if response.status_code != 200:
                    response = await client.get(base_url, params=payload, headers=headers)
            except Exception:
                response = await client.get(base_url, params=payload, headers=headers)

        if response.status_code != 200:
            raise RuntimeError(f"GPT-SoVITS API error: {response.status_code} - {response.text}")

        self._atomic_write_bytes(path, response.content)

    async def _generate_doubao_audio(self, text: str, voice: str, rate: str, path: Path) -> None:
        access_token, app_id, cluster = self._doubao_settings()
        if not access_token:
            raise ValueError("豆包 Access Token 未配置。请在 设置 → Doubao 中填写 doubao_access_token。")
        if not app_id:
            raise ValueError("豆包 App ID 未配置。请在 设置 → Doubao 中填写 doubao_app_id。")

        speed_ratio = 1.0
        if rate:
            import re as _re
            match = _re.match(r"^([+-]?)(\d+)%$", rate.strip())
            if match:
                sign = match.group(1)
                percent = float(match.group(2)) / 100.0
                if sign == "-":
                    speed_ratio = max(0.1, 1.0 - percent)
                else:
                    speed_ratio = min(2.0, 1.0 + percent)

        audio_bytes = await doubao_tts_synthesize(
            text=text,
            voice_type=voice,
            access_token=access_token,
            appid=app_id,
            cluster=cluster,
            encoding="mp3",
            speed_ratio=speed_ratio,
        )
        self._atomic_write_bytes(path, audio_bytes)

    async def _generate_edge_audio(self, text: str, voice: str, rate: str, path: Path) -> None:
        if edge_tts is None:
            raise RuntimeError("edge-tts Python 依赖未安装。")
        try:
            communicator = edge_tts.Communicate(text, voice, rate=rate)
            import tempfile as _tf
            _fd, _tmp = _tf.mkstemp(dir=str(path.parent), suffix=".tmp")
            os.close(_fd)
            try:
                await asyncio.wait_for(
                    communicator.save(_tmp), timeout=EDGE_TTS_TIMEOUT_SECONDS
                )
                os.replace(_tmp, str(path))
            except BaseException:
                try:
                    os.unlink(_tmp)
                except OSError:
                    pass
                raise
        except asyncio.TimeoutError as exc:
            raise RuntimeError(
                f"Edge TTS 朗读超时（超过 {EDGE_TTS_TIMEOUT_SECONDS:.0f} 秒未收到微软语音服务响应）。"
                "请检查网络连接，或稍后再试。"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"Edge TTS 朗读生成失败 ({exc})。请检查网络是否能够正常访问微软 Edge 语音服务。") from exc

    def _resolve_qwen_voice_for_model(self, voice: str, model_name: str) -> str:
        """Validate the voice against the model's voice family.

        qwen-audio-3.0-tts-* models only accept the longan voice family, while
        qwen3-tts-* models only accept the Cherry/Ono Anna family. Mixing them
        makes the DashScope SDK return None audio with no useful error, so we
        fail fast with an actionable message. Unknown (custom/cloned) voices are
        passed through untouched.
        """
        if is_qwen_audio_tts_model(model_name):
            if any(v["name"] == voice for v in QWEN_FLASH_VOICES):
                raise ValueError(
                    f"音色 {voice} 属于 qwen3-tts 系列，与模型 {model_name} 不兼容。"
                    f"qwen-audio-3.0-tts 系列请使用龙系列音色（如 {DEFAULT_QWEN_AUDIO_TTS_VOICE}），"
                    "或在模型版本中选择 qwen3-tts-flash。"
                )
            return voice
        if any(v["name"] == voice for v in QWEN_AUDIO_TTS_VOICES):
            raise ValueError(
                f"音色 {voice} 属于 qwen-audio-3.0-tts 系列，与模型 {model_name} 不兼容。"
                "qwen3-tts 系列请使用 Cherry/Ono Anna 等音色，"
                "或在模型版本中选择 qwen-audio-3.0-tts-flash。"
            )
        return voice

    async def _generate_qwen_flash_audio(self, text: str, voice: str, path: Path, model: str | None = None) -> None:
        api_key = self._dashscope_key()
        if not api_key:
            raise RuntimeError("DashScope API Key is not configured.")
        try:
            import dashscope
            from dashscope.audio.tts_v2 import SpeechSynthesizer
        except ImportError as exc:
            raise RuntimeError("dashscope SDK is not installed on backend.") from exc

        dashscope.api_key = api_key
        model_name = model or DEFAULT_QWEN_FLASH_MODEL
        voice_name = self._resolve_qwen_voice_for_model(voice, model_name)
        synthesizer = SpeechSynthesizer(model=model_name, voice=voice_name)
        # dashscope SDK 的 call() 是同步阻塞的网络调用，放到专用线程池里跑，避免卡住事件循环
        audio = await _run_tts_blocking(synthesizer.call, text)
        if not audio:
            # SDK 合成失败时 call() 返回 None（不会抛异常），常见原因是音色与模型
            # 不兼容或配额/网络问题。带上 request_id 方便排查。
            request_id = ""
            try:
                request_id = synthesizer.get_last_request_id() or ""
            except Exception:
                pass
            raise RuntimeError(
                f"Qwen TTS 合成失败：服务未返回音频数据（模型 {model_name}，音色 {voice_name}"
                f"{f'，request_id: {request_id}' if request_id else ''}）。"
                "请确认音色与模型系列匹配（qwen-audio-3.0-tts 用龙系列音色，qwen3-tts 用 Cherry/Ono Anna 等音色），"
                "并检查 DashScope 配额与网络。"
            )
        self._atomic_write_bytes(path, audio)

    async def _generate_minimax_audio(self, text: str, voice: str, path: Path, model: str | None = None) -> None:
        api_key, base_url = self._minimax_settings()
        if not api_key:
            raise RuntimeError("MiniMax API Key is not configured.")

        model_name = model or DEFAULT_MINIMAX_MODEL
        payload = {
            "model": model_name,
            "text": text,
            "voice_setting": {
                "voice_id": voice,
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0,
            },
            "stream": False,
            "audio_setting": {
                "sample_rate": 32000,
                "format": "mp3",
            },
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(base_url, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"MiniMax API error: {response.status_code} - {response.text}")

        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError("MiniMax returned an invalid JSON payload.") from exc

        if data.get("base_resp", {}).get("status_code", 0) != 0:
            raise RuntimeError(data.get("base_resp", {}).get("status_msg", "MiniMax TTS failed."))

        audio_obj = data.get("data", {}).get("audio")
        if isinstance(audio_obj, dict):
            audio_hex = str(audio_obj.get("data", "")).strip()
        elif isinstance(audio_obj, str):
            audio_hex = audio_obj.strip()
        else:
            audio_hex = str(data.get("audio", "")).strip()

        if not audio_hex:
            raise RuntimeError("MiniMax returned no audio data.")

        self._atomic_write_bytes(path, bytes.fromhex(audio_hex))

    async def _generate_xiaomi_audio(self, text: str, voice: str, path: Path, model: str | None = None) -> None:
        api_key, base_url = self._xiaomi_settings()
        if not api_key:
            raise RuntimeError("Xiaomi API Key is not configured.")

        url = f"{base_url}/v1/chat/completions"
        model_name = model or DEFAULT_XIAOMI_MODEL
        payload = {
            "model": model_name,
            "messages": [{"role": "assistant", "content": text}],
            "audio": {
                "format": "mp3",
                "voice": voice or "mimo_default",
            },
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Run asynchronous HTTP request
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)

        if response.status_code != 200:
            raise RuntimeError(f"Xiaomi API error: {response.status_code} - {response.text}")

        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError("Xiaomi returned an invalid JSON payload.") from exc

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError(f"Xiaomi TTS returned no choices. Response: {data}")

        message = choices[0].get("message", {})
        audio_data = message.get("audio", {}).get("data", "")
        if not audio_data:
            raise RuntimeError(f"Xiaomi TTS returned no audio data. Response: {data}")

        import base64
        audio_bytes = base64.b64decode(audio_data)
        self._atomic_write_bytes(path, audio_bytes)

    async def _generate_openai_audio(self, text: str, voice: str, rate: str, path: Path, model: str | None = None) -> None:
        self.config.reload()
        api_key = str(self.config.get_all().get("api_keys", {}).get("openai_api_key", "")).strip()
        if not api_key:
            raise RuntimeError("OpenAI API Key is not configured.")

        base_url = str(self.config.get_all().get("api_urls", {}).get("OpenAI", "")).strip()
        if not base_url:
            base_url = "https://api.openai.com/v1"
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")

        speed = 1.0
        if rate:
            match = re.match(r"^([+-]?)(\d+)%$", rate.strip())
            if match:
                sign = match.group(1)
                percent = float(match.group(2)) / 100.0
                if sign == "-":
                    speed = max(0.25, 1.0 - percent)
                else:
                    speed = min(4.0, 1.0 + percent)

        model_name = model or self.config.get_provider_settings("OpenAI").get("tts_default", "").strip() or self.config.get_provider_settings("OpenAI").get("model", "").strip() or "tts-1"

        payload = {
            "model": model_name,
            "input": text,
            "voice": voice.lower() if voice else "alloy",
            "response_format": "mp3",
            "speed": speed,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{base_url}/audio/speech", json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"OpenAI TTS API error: {response.status_code} - {response.text}")

        self._atomic_write_bytes(path, response.content)

    async def _generate_elevenlabs_audio(self, text: str, voice: str, path: Path, model: str | None = None) -> None:
        self.config.reload()
        api_key = str(self.config.get_all().get("api_keys", {}).get("elevenlabs_api_key", "")).strip()
        if not api_key:
            raise RuntimeError("ElevenLabs API Key is not configured.")

        base_url = str(self.config.get_all().get("api_urls", {}).get("ElevenLabs", "")).strip()
        if not base_url:
            base_url = "https://api.elevenlabs.io/v1"
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")

        voice_id = voice or "21m0aEP3W9qOfdrWSyXx"
        url = f"{base_url}/text-to-speech/{voice_id}"

        model_name = model or self.config.get_provider_settings("ElevenLabs").get("tts_default", "").strip() or self.config.get_provider_settings("ElevenLabs").get("model", "").strip() or "eleven_multilingual_v2"

        payload = {
            "text": text,
            "model_id": model_name,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
            },
        }
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"ElevenLabs TTS API error: {response.status_code} - {response.text}")

        self._atomic_write_bytes(path, response.content)

    async def _fetch_elevenlabs_voices(self) -> list[dict[str, Any]]:
        self.config.reload()
        api_key = str(self.config.get_all().get("api_keys", {}).get("elevenlabs_api_key", "")).strip()
        if not api_key:
            return ELEVENLABS_VOICES
        
        base_url = str(self.config.get_all().get("api_urls", {}).get("ElevenLabs", "")).strip()
        if not base_url:
            base_url = "https://api.elevenlabs.io/v1"
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        base_url = base_url.rstrip("/")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"{base_url}/voices", headers={"xi-api-key": api_key})
                if response.status_code == 200:
                    data = response.json()
                    voices_data = data.get("voices", [])
                    if voices_data:
                        loaded = []
                        for v in voices_data:
                            labels = v.get("labels", {})
                            gender = labels.get("gender", "Unknown")
                            accent = labels.get("accent", "multi")
                            loaded.append({
                                "name": v.get("voice_id"),
                                "short_name": f"{v.get('name')} (ElevenLabs)",
                                "locale": accent,
                                "gender": gender.capitalize(),
                            })
                        return loaded
        except Exception:
            pass
        return ELEVENLABS_VOICES

    def detect_engine_by_voice(self, voice: str | None) -> str:
        if not voice:
            return TTS_ENGINE_EDGE
        # Check ChatTTS voices
        if any(v["name"] == voice for v in CHATTTS_VOICES) or (voice and voice.isdigit()) or (voice and voice.startswith("seed_")):
            return TTS_ENGINE_CHATTTS
        # Check GPT-SoVITS voices
        if voice == "default" or (voice and voice.startswith("gpt_sovits_")):
            return TTS_ENGINE_GPT_SOVITS
        # Check OpenAI voices
        if any(v["name"] == voice for v in OPENAI_VOICES):
            return TTS_ENGINE_OPENAI
        # Check ElevenLabs voices
        if any(v["name"] == voice for v in ELEVENLABS_VOICES) or (voice and len(voice) == 20 and voice.isalnum()):
            return TTS_ENGINE_ELEVENLABS
        # 1. Check Qwen custom/designed/cloned prefixes or names
        if voice.startswith(("qwen3-tts-vd", "qwen3-tts-vc")):
            return TTS_ENGINE_QWEN_FLASH
        if any(v["name"] == voice for v in QWEN_FLASH_VOICES):
            return TTS_ENGINE_QWEN_FLASH
        if any(v["name"] == voice for v in QWEN_AUDIO_TTS_VOICES):
            return TTS_ENGINE_QWEN_FLASH
        # Check Doubao voices
        if is_doubao_voice(voice):
            return TTS_ENGINE_DOUBAO
        # 2. Check MiniMax voices
        if any(v["name"] == voice for v in MINIMAX_VOICES):
            return TTS_ENGINE_MINIMAX
        # 3. Check Xiaomi voices
        if any(v["name"] == voice for v in XIAOMI_VOICES):
            return TTS_ENGINE_XIAOMI
        # 4. Check standard edge names
        if voice.endswith("Neural") or "-" in voice:
            return TTS_ENGINE_EDGE
        # Fallback default for other custom voice design/clones
        return TTS_ENGINE_QWEN_FLASH

    async def generate_audio(
        self,
        text: str,
        voice: str | None,
        rate: str = "+0%",
        engine: str | None = None,
        model: str | None = None,
    ) -> TTSAudioResult:
        cleaned = self._clean_text(text)

        # Keep backward compatibility for callers that omit engine while passing
        # a provider-specific voice, but do not override explicit non-Edge engines.
        normalized_requested_engine = self._normalize_engine(engine)
        if engine is None or normalized_requested_engine == TTS_ENGINE_EDGE:
            detected_engine = self.detect_engine_by_voice(voice)
        else:
            detected_engine = normalized_requested_engine

        normalized_engine = detected_engine

        if normalized_engine == TTS_ENGINE_EDGE:
            selected_voice = self._resolve_edge_voice_for_text(cleaned, voice) if voice else self._detect_edge_voice(cleaned)
        elif normalized_engine == TTS_ENGINE_QWEN_FLASH:
            if voice:
                selected_voice = voice
            elif is_qwen_audio_tts_model(model):
                selected_voice = DEFAULT_QWEN_AUDIO_TTS_VOICE
            else:
                selected_voice = QWEN_FLASH_VOICES[0]["name"]
        elif normalized_engine == TTS_ENGINE_MINIMAX:
            selected_voice = voice or MINIMAX_VOICES[0]["name"]
        elif normalized_engine == TTS_ENGINE_OPENAI:
            selected_voice = voice or OPENAI_VOICES[0]["name"]
        elif normalized_engine == TTS_ENGINE_ELEVENLABS:
            selected_voice = voice or ELEVENLABS_VOICES[0]["name"]
        elif normalized_engine == TTS_ENGINE_CHATTTS:
            selected_voice = voice or CHATTTS_VOICES[0]["name"]
        elif normalized_engine == TTS_ENGINE_GPT_SOVITS:
            selected_voice = voice or GPT_SOVITS_VOICES[0]["name"]
        elif normalized_engine == TTS_ENGINE_DOUBAO:
            selected_voice = voice or DEFAULT_DOUBAO_TTS_VOICE
        else:
            selected_voice = voice or XIAOMI_VOICES[0]["name"]

        extension, media_type = self._audio_profile_for_engine(normalized_engine)
        filename = self._make_filename(cleaned, selected_voice, rate, normalized_engine, extension, model=model)
        path = self.output_dir / filename

        if path.exists() and path.stat().st_size > 0:
            return TTSAudioResult(
                file_path=str(path),
                voice=selected_voice,
                engine=normalized_engine,
                media_type=media_type,
                filename=f"tts_output.{extension}",
                cache_hit=True,
            )

        if normalized_engine == TTS_ENGINE_EDGE:
            await self._generate_edge_audio(cleaned, selected_voice, rate, path)
        elif normalized_engine == TTS_ENGINE_QWEN_FLASH:
            await self._generate_qwen_flash_audio(cleaned, selected_voice, path, model=model)
        elif normalized_engine == TTS_ENGINE_MINIMAX:
            await self._generate_minimax_audio(cleaned, selected_voice, path, model=model)
        elif normalized_engine == TTS_ENGINE_OPENAI:
            await self._generate_openai_audio(cleaned, selected_voice, rate, path, model=model)
        elif normalized_engine == TTS_ENGINE_ELEVENLABS:
            await self._generate_elevenlabs_audio(cleaned, selected_voice, path, model=model)
        elif normalized_engine == TTS_ENGINE_CHATTTS:
            await self._generate_chattts_audio(cleaned, selected_voice, path)
        elif normalized_engine == TTS_ENGINE_GPT_SOVITS:
            await self._generate_gpt_sovits_audio(cleaned, selected_voice, path)
        elif normalized_engine == TTS_ENGINE_DOUBAO:
            await self._generate_doubao_audio(cleaned, selected_voice, rate, path)
        else:
            await self._generate_xiaomi_audio(cleaned, selected_voice, path, model=model)

        if not path.exists() or path.stat().st_size == 0:
            raise RuntimeError("Failed to generate audio file.")

        return TTSAudioResult(
            file_path=str(path),
            voice=selected_voice,
            engine=normalized_engine,
            media_type=media_type,
            filename=f"tts_output.{extension}",
            cache_hit=False,
        )

    async def generate_dialogue_audio(
        self,
        text: str,
        voice_a: str | None,
        voice_b: str | None,
        rate: str = "+0%",
        engine: str = "edge",
        engine_b: str | None = None,
        model: str | None = None,
        model_b: str | None = None,
    ) -> TTSAudioResult:
        import uuid
        
        # 1. Parse dialogue text into alternating script lines
        lines = parse_script_with_fallback(text)

        if not lines:
            raise ValueError("No valid dialogue lines found.")

        # 2. Synthesize each line using the respective speaker's voice
        segment_paths = []
        segment_results: list[TTSAudioResult] = []
        used_voice_by_role: dict[str, str] = {}
        for idx, line in enumerate(lines):
            selected_voice = voice_a if line["role"] == "A" else voice_b
            selected_engine = engine if line["role"] == "A" else (engine_b or engine)
            selected_model = model if line["role"] == "A" else (model_b or model)
            result = await self.generate_audio(
                text=line["text"],
                voice=selected_voice,
                rate=rate,
                engine=selected_engine,
                model=selected_model,
            )
            segment_results.append(result)
            used_voice_by_role.setdefault(line["role"], result.voice)
            segment_paths.append(Path(result.file_path))

        # 3. Merge audio files using pydub with a 250ms silence gap.
        output_name = f"dialogue_{uuid.uuid4().hex[:8]}.mp3"
        output_path = self.output_dir / output_name

        try:
            from pydub import AudioSegment
            combined = None
            silence = AudioSegment.silent(duration=250)
            for idx, segment in enumerate(segment_paths):
                audio = AudioSegment.from_file(str(segment))
                if combined is None:
                    combined = audio
                else:
                    combined += silence + audio
            if combined is not None:
                combined.export(str(output_path), format="mp3", bitrate="192k")
        except ImportError as exc:
            raise RuntimeError("pydub is required to merge dialogue audio segments.") from exc
        except Exception as exc:
            raise RuntimeError(f"Failed to merge dialogue audio segments: {exc}") from exc

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Failed to generate dialogue audio file.")

        used_engines = " + ".join(dict.fromkeys(result.engine for result in segment_results))
        used_voices = " + ".join(
            voice for voice in [used_voice_by_role.get("A", ""), used_voice_by_role.get("B", "")] if voice
        )
        return TTSAudioResult(
            file_path=str(output_path),
            voice=used_voices,
            engine=used_engines,
            media_type=MEDIA_TYPE_MP3,
            filename="tts_dialogue.mp3",
            cache_hit=False,
        )

    def _clean_edge_voice_short_name(self, short_name: str) -> str:
        if "-" in short_name:
            short_name = short_name.split("-")[-1]
        if short_name.endswith("Neural"):
            short_name = short_name[:-6]
        return short_name

    async def list_voices(
        self,
        locale: str | None = None,
        engine: str = TTS_ENGINE_EDGE,
        model: str | None = None,
    ) -> list[dict[str, Any]]:
        normalized_engine = self._normalize_engine(engine)
        if normalized_engine == TTS_ENGINE_CHATTTS:
            return self._filter_by_locale(CHATTTS_VOICES, locale)
        if normalized_engine == TTS_ENGINE_GPT_SOVITS:
            local_clones = self._get_local_gpt_sovits_voices()
            return self._filter_by_locale(GPT_SOVITS_VOICES + local_clones, locale)
        if normalized_engine == TTS_ENGINE_DOUBAO:
            return self._filter_by_locale(DOUBAO_VOICES, locale)
        if normalized_engine == TTS_ENGINE_QWEN_FLASH:
            # The two Qwen TTS families use incompatible voice sets; when the
            # caller tells us the model, return only voices that work with it.
            if is_qwen_audio_tts_model(model):
                return self._filter_by_locale(QWEN_AUDIO_TTS_VOICES, locale)
            return self._filter_by_locale(QWEN_FLASH_VOICES, locale)
        if normalized_engine == TTS_ENGINE_MINIMAX:
            return self._filter_by_locale(MINIMAX_VOICES, locale)
        if normalized_engine == TTS_ENGINE_XIAOMI:
            return self._filter_by_locale(XIAOMI_VOICES, locale)
        if normalized_engine == TTS_ENGINE_OPENAI:
            return self._filter_by_locale(OPENAI_VOICES, locale)
        if normalized_engine == TTS_ENGINE_ELEVENLABS:
            voices = await self._fetch_elevenlabs_voices()
            return self._filter_by_locale(voices, locale)

        if edge_tts is None:
            return self._filter_by_locale(FALLBACK_EDGE_VOICES, locale)

        try:
            voices_manager = await edge_tts.VoicesManager.create()
            voices = voices_manager.voices
            normalized = [
                {
                    "name": item.get("Name", ""),
                    "short_name": self._clean_edge_voice_short_name(item.get("ShortName", "")),
                    "locale": item.get("Locale", ""),
                    "gender": item.get("Gender", ""),
                }
                for item in voices
            ]
            normalized = [v for v in normalized if v["name"]]
            return self._filter_by_locale(normalized, locale)
        except Exception:
            return self._filter_by_locale(FALLBACK_EDGE_VOICES, locale)

    async def stream_azure_tts_with_timestamps(self, text: str, voice: str):
        def sse(payload: dict[str, Any]) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        if speechsdk is None:
            yield sse({"type": "error", "message": "azure-cognitiveservices-speech not installed"})
            return

        clean_text = str(text or "").strip()
        clean_voice = str(voice or "").strip() or "zh-CN-YunxiNeural"
        if not clean_text:
            yield sse({"type": "error", "message": "Text is required"})
            return

        api_keys = self.config.get_all().get("api_keys", {})
        speech_key = api_keys.get("azure", "")
        # Try to parse region if provided, else default to eastus
        api_urls = self.config.get_all().get("api_urls", {})
        speech_region = api_urls.get("azure", "eastus")

        if not speech_key:
            yield sse({"type": "error", "message": "Azure Speech key not configured"})
            return

        speech_config = speechsdk.SpeechConfig(subscription=speech_key, region=speech_region)
        speech_config.speech_synthesis_voice_name = clean_voice
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz48KBitRateMonoMp3
        )

        pull_stream = speechsdk.audio.PullAudioOutputStream()
        audio_output = speechsdk.audio.AudioOutputConfig(stream=pull_stream)
        synthesizer = speechsdk.SpeechSynthesizer(
            speech_config=speech_config,
            audio_config=audio_output,
        )

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        def enqueue(message: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, message)

        def on_word_boundary(evt: Any) -> None:
            duration = getattr(evt, "duration", 0)
            if hasattr(duration, "total_seconds"):
                duration_ms = duration.total_seconds() * 1000
            else:
                duration_ms = float(duration or 0) / 10000
            enqueue({
                "type": "word",
                "text": str(getattr(evt, "text", "")),
                "offset_ms": float(getattr(evt, "audio_offset", 0) or 0) / 10000,
                "duration_ms": duration_ms,
            })

        synthesizer.synthesis_word_boundary.connect(on_word_boundary)

        def synthesize() -> None:
            safe_voice = html.escape(clean_voice, quote=True)
            safe_text = html.escape(clean_text, quote=False)
            ssml = f"""<speak version='1.0' xml:lang='zh-CN'>
              <voice name='{safe_voice}'>{safe_text}</voice>
            </speak>"""
            result = synthesizer.speak_ssml_async(ssml).get()
            if result.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
                enqueue({"type": "error", "message": str(getattr(result, "cancellation_details", ""))})
            enqueue({"type": "done"})

        thread = threading.Thread(target=synthesize, daemon=True)
        thread.start()

        while True:
            chunk = bytearray(4096)
            bytes_read = await _run_tts_blocking(pull_stream.read, chunk)

            if bytes_read > 0:
                audio_base64 = base64.b64encode(chunk[:bytes_read]).decode()
                yield sse({"type": "audio", "data": audio_base64})

            while not queue.empty():
                msg = queue.get_nowait()
                if msg["type"] == "done":
                    if bytes_read == 0:
                        return
                else:
                    yield sse(msg)

            if bytes_read == 0:
                thread.join(0.1)
                if not thread.is_alive() and queue.empty():
                    break
                await asyncio.sleep(0.01)
