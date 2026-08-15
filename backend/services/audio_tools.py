"""ffmpeg/ffprobe helpers for transcription preprocessing.

The synchronous ASR engines this app calls all have hard input limits
(Qwen-Audio-3.0-ASR-Flash: <=10MB and <=5 minutes; OpenAI Whisper: <=25MB).
Users, however, regularly want to transcribe long recordings and the audio
track of video files. This module provides the local preprocessing that
bridges the gap:

- ``probe_media``: read duration / stream info via ffprobe.
- ``transcode_for_asr``: normalize to 16kHz mono low-bitrate MP3 (or PCM WAV
  when no MP3 encoder exists locally), which both extracts the audio track
  from video containers and shrinks oversized uploads by 10-50x.
- ``transcode_and_split``: single-pass re-encode + segment for long media,
  cutting at exact time boundaries without ever materializing a giant
  intermediate file.

All subprocess work runs through ``asyncio.to_thread`` so the event loop is
never blocked. Every function degrades with an explicit error when the
ffmpeg binaries are missing, letting callers fall back to the legacy path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Extensions that are media containers with a video track (audio must be
# extracted before ASR). Pure audio containers are handled by the ASR APIs
# directly (or transcoded when oversized).
VIDEO_CONTAINER_SUFFIXES = {
    ".mp4",
    ".m4v",
    ".mkv",
    ".mov",
    ".avi",
    ".flv",
    ".wmv",
    ".webm",
    ".ts",
    ".3gp",
    ".mpg",
    ".mpeg",
}

# Target encoding for normalized audio. 16kHz mono keeps ASR accuracy (all
# supported engines downsample to 16kHz internally). MP3 at 48kbps stays
# ~4KB/s (a 4-minute chunk is under 1.2MB); when the local ffmpeg build has
# no MP3 encoder we fall back to 16-bit PCM WAV (~32KB/s — a 4-minute chunk
# is ~7.5MB, still under every provider's per-request size cap).
#
# Deliberately NOT using the Windows MediaFoundation MP3 encoder (mp3_mf):
# it cannot encode 16kHz and its longer outputs carry broken duration
# metadata, which makes chunk-boundary bookkeeping unreliable.
NORMALIZED_SAMPLE_RATE = "16000"
NORMALIZED_CHANNELS = "1"
NORMALIZED_MP3_BITRATE = "48k"

# MP3 encoders in preference order.
_MP3_ENCODER_CANDIDATES = ("libmp3lame", "libshine")

_mp3_encoder_cache: str | None = ""  # "" = unresolved


class AudioToolsError(RuntimeError):
    """Raised when local media preprocessing fails."""


def detect_mp3_encoder() -> str | None:
    """Return the best available MP3 encoder name, or None if there is none.

    The result is cached; the ffmpeg binary is queried at most once.
    """
    global _mp3_encoder_cache
    if _mp3_encoder_cache != "":
        return None if _mp3_encoder_cache == "-" else _mp3_encoder_cache

    encoder: str | None = None
    try:
        result = _run_sync(["ffmpeg", "-hide_banner", "-encoders"], timeout=30.0)
        if result.returncode == 0:
            available: set[str] = set()
            for line in (result.stdout or "").splitlines():
                # Encoder list rows look like: " A....D libmp3lame   ..."
                parts = line.split()
                if len(parts) >= 2 and parts[0].startswith("A"):
                    available.add(parts[1])
            for candidate in _MP3_ENCODER_CANDIDATES:
                if candidate in available:
                    encoder = candidate
                    break
    except (OSError, subprocess.SubprocessError):
        encoder = None

    _mp3_encoder_cache = encoder or "-"
    return encoder


def normalized_suffix() -> str:
    """File suffix used for normalized intermediate audio."""
    return ".mp3" if detect_mp3_encoder() else ".wav"


async def warmup_mp3_encoder() -> None:
    """Resolve the encoder cache off the event loop.

    The first detect_mp3_encoder() call runs ``ffmpeg -encoders`` as a
    blocking subprocess; every later call is a cache hit. Async pipelines
    should await this once up front so the sync helpers (normalized_suffix,
    asr_limits, _asr_codec_args) never run that subprocess on the event loop.
    """
    await asyncio.to_thread(detect_mp3_encoder)


def asr_limits(sync_max: int, chunk: int) -> tuple[int, int]:
    """Return (sync_max_seconds, chunk_seconds) tuned to the local codec.

    PCM WAV at 16kHz mono is ~32KB/s, and base64 inflates request payloads
    by 4/3 — a 240s WAV chunk is ~7.7MB raw but ~10.2MB encoded, brushing
    against Qwen's 10MB per-call cap. When only the WAV fallback is
    available, both thresholds shrink so encoded chunks stay well under it.
    """
    if detect_mp3_encoder():
        return sync_max, chunk
    return 210, 200


@dataclass(slots=True)
class MediaProbe:
    duration_seconds: float
    size_bytes: int
    has_video_stream: bool
    has_audio_stream: bool


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _run_sync(command: list[str], timeout: float = 1800.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


async def _run(command: list[str], timeout: float = 1800.0) -> subprocess.CompletedProcess:
    return await asyncio.to_thread(_run_sync, command, timeout)


async def probe_media(path: Path) -> MediaProbe:
    """Probe a media file with ffprobe. Raises AudioToolsError on failure."""
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = await _run(command, timeout=120.0)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-300:]
        raise AudioToolsError(f"ffprobe failed for {path.name}: {detail}")

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AudioToolsError(f"ffprobe returned invalid JSON: {exc}") from exc

    duration = 0.0
    fmt = payload.get("format") or {}
    try:
        duration = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0

    has_video = False
    has_audio = False
    for stream in payload.get("streams") or []:
        codec_type = str(stream.get("codec_type") or "")
        if codec_type == "video":
            has_video = True
        elif codec_type == "audio":
            has_audio = True
        # Per-stream duration fallback (some containers omit format.duration).
        if duration <= 0.0:
            try:
                stream_duration = float(stream.get("duration") or 0.0)
                if stream_duration > duration:
                    duration = stream_duration
            except (TypeError, ValueError):
                pass

    size_bytes = 0
    try:
        size_bytes = path.stat().st_size
    except OSError:
        pass

    return MediaProbe(
        duration_seconds=duration,
        size_bytes=size_bytes,
        has_video_stream=has_video,
        has_audio_stream=has_audio,
    )


def _asr_codec_args() -> tuple[list[str], str]:
    """(codec args, output suffix) for the best local ASR-friendly encoding."""
    encoder = detect_mp3_encoder()
    if encoder:
        args = ["-c:a", encoder]
        if encoder in {"libmp3lame", "libshine"}:
            args += ["-b:a", NORMALIZED_MP3_BITRATE]
        return args, ".mp3"
    return ["-c:a", "pcm_s16le"], ".wav"


async def transcode_for_asr(source: Path, output_path: Path) -> Path:
    """Normalize any media file to 16kHz mono audio (first audio stream).

    Output is MP3 when the local ffmpeg build has an MP3 encoder, otherwise
    16-bit PCM WAV. Works for both video containers (extracts the audio track)
    and oversized audio files (re-encodes to a small file).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    codec_args, _ = _asr_codec_args()
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vn",  # drop video streams
        "-map",
        "0:a:0?",  # first audio stream; '?' tolerates odd inputs
        "-ac",
        NORMALIZED_CHANNELS,
        "-ar",
        NORMALIZED_SAMPLE_RATE,
        *codec_args,
        str(output_path),
    ]
    result = await _run(command)
    if result.returncode != 0 or not output_path.is_file() or output_path.stat().st_size == 0:
        detail = (result.stderr or result.stdout or "").strip()[-400:]
        raise AudioToolsError(
            f"ffmpeg transcode failed for {source.name} "
            f"(no usable audio track?): {detail}"
        )
    return output_path


async def transcode_and_split(
    source: Path, chunk_seconds: int, output_dir: Path
) -> list[Path]:
    """Single-pass transcode + segment for long media.

    Combines normalization and splitting into one ffmpeg run: re-encoding
    (not stream copy) so segment boundaries land at exact multiples of
    ``chunk_seconds``, and no giant intermediate file is ever written —
    a 12-hour source never materializes as a 12-hour WAV on disk first.
    Returns chunk paths in order.
    """
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be positive.")
    output_dir.mkdir(parents=True, exist_ok=True)
    codec_args, suffix = _asr_codec_args()
    pattern = str(output_dir / f"chunk_%04d{suffix}")
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-map",
        "0:a:0?",
        "-ac",
        NORMALIZED_CHANNELS,
        "-ar",
        NORMALIZED_SAMPLE_RATE,
        *codec_args,
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        pattern,
    ]
    result = await _run(command)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-400:]
        raise AudioToolsError(f"ffmpeg transcode+split failed for {source.name}: {detail}")

    chunks = sorted(output_dir.glob(f"chunk_*{suffix}"))
    chunks = [chunk for chunk in chunks if chunk.stat().st_size > 0]
    if not chunks:
        raise AudioToolsError(
            f"ffmpeg produced no chunks for {source.name} (no usable audio track?)"
        )
    return chunks


def cleanup_paths(paths: list[Path]) -> None:
    """Best-effort removal of temporary preprocessing artifacts."""
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            logger.debug("Could not remove temp file: %s", path)
