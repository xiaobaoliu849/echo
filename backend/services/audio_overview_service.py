from __future__ import annotations
import asyncio
import logging
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db_utils import ClosingConnection, get_db_connection
from .llm_service import LLMService
from .evermem_config import EverMemConfig
from .tts_service import TTSService
from .script_parser import parse_script_from_text, parse_script_with_fallback, normalize_script_lines


PROMPT_TEMPLATE_ZH = """你是一个播客脚本编写专家。请根据以下话题生成一段双人对话脚本。

话题：{topic}

要求：
1. 对话包含两个角色：A（主持人）和 B（嘉宾专家）
2. 生成 {turn_count} 轮对话（每轮包含 A 和 B 各说一段）
3. 对话自然流畅，像真实的播客节目
4. A 负责引导话题、提问；B 负责解答、分享见解
5. 包含开场白和结束语
6. 每句话控制在 50-150 字之间，适合语音朗读

输出格式（严格遵循，每行一句）：
A: [主持人的话]
B: [嘉宾的话]
A: [主持人的话]
B: [嘉宾的话]
...

请直接输出对话内容，不要添加其他说明。"""

PROMPT_TEMPLATE_EN = """You are a podcast script writing expert. Please generate a two-person dialogue script based on the following topic.

Topic: {topic}

IMPORTANT: You MUST write ALL dialogue content in English, even if the topic is in another language.

Requirements:
1. The dialogue includes two roles: A (Host) and B (Guest Expert)
2. Generate {turn_count} rounds of dialogue (each round includes one statement from A and one from B)
3. The dialogue should be natural and fluent, like a real podcast
4. A is responsible for guiding the topic and asking questions; B is responsible for answering and sharing insights
5. Include an opening and closing
6. Keep each statement between 30-100 words
7. ALL content MUST be in English

Output format (strictly follow, one statement per line):
A: [Host's statement in English]
B: [Guest's statement in English]
A: [Host's statement in English]
B: [Guest's statement in English]
...

Please output the dialogue content directly in English without additional explanation."""


SUPPORTED_MERGE_STRATEGIES = {"auto", "pydub", "ffmpeg", "concat"}
SUPPORTED_INTRO_MUSIC_STYLES = {"warm", "bright", "calm"}
logger = logging.getLogger(__name__)




class AudioOverviewServiceError(Exception):
    def __init__(self, *, code: str, message: str, meta: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.meta = meta or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "meta": self.meta,
        }


class AudioOverviewService:
    def __init__(
        self,
        db_path: Path | None = None,
        llm_service: LLMService | None = None,
        tts_service: TTSService | None = None,
        output_dir: Path | None = None,
    ):
        self.db_path = db_path or self._default_db_path()
        self.llm_service = llm_service or LLMService()
        self.tts_service = tts_service or TTSService()
        self.output_dir = output_dir or self._default_output_dir()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._last_cleanup_monotonic = time.monotonic()
        self._init_db()
        self._cleanup_old_output_files()

    def _cleanup_old_output_files(self, max_files: int = 200, max_age_hours: int = 72) -> None:
        """Remove stale podcast audio so APPDATA temp usage stays bounded.

        Covers finished episodes, superseded takes, and orphaned intro-music
        files — nothing else evicts this directory.
        """
        try:
            stats = [
                (path, path.stat().st_mtime)
                for path in self.output_dir.iterdir()
                if path.is_file() and path.suffix == ".mp3"
            ]
        except OSError:
            return
        # Single pass over pre-collected stats: a file vanishing mid-sweep
        # cannot crash the caller.
        cutoff = time.time() - max_age_hours * 3600
        survivors: list[tuple[Path, float]] = []
        for path, mtime in stats:
            if mtime < cutoff:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue
            else:
                survivors.append((path, mtime))
        if len(survivors) > max_files:
            survivors.sort(key=lambda item: item[1])
            for path, _ in survivors[: len(survivors) - max_files]:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    continue

    async def _maybe_cleanup_old_files(self) -> None:
        """Throttled lazy eviction for long-running processes."""
        now = time.monotonic()
        if now - self._last_cleanup_monotonic < 600:
            return
        self._last_cleanup_monotonic = now
        await asyncio.to_thread(self._cleanup_old_output_files)

    def _unlink_managed_audio(self, path_text: str | None) -> None:
        """Delete a podcast audio file, but only if this service owns it."""
        if not path_text:
            return
        try:
            path = Path(str(path_text)).expanduser().resolve()
            if self.output_dir.resolve() in path.parents and path.is_file():
                path.unlink()
        except OSError:
            pass

    @staticmethod
    def _default_db_path() -> Path:
        from .config_loader import get_data_file_path

        return get_data_file_path("voice_spirit.db")

    @staticmethod
    def _default_output_dir() -> Path:
        from .config_loader import get_data_dir

        return get_data_dir() / "temp_audio" / "audio_overview"

    def _connect(self) -> sqlite3.Connection:
        return get_db_connection(self.db_path)

    @staticmethod
    def _clean_language(value: str | None) -> str:
        text = str(value or "").strip().lower()
        if text.startswith("en"):
            return "en"
        return "zh"

    @staticmethod
    def _default_voice_pair(language: str) -> tuple[str, str]:
        if language == "en":
            return ("en-US-GuyNeural", "en-US-JennyNeural")
        return ("zh-CN-YunxiNeural", "zh-CN-XiaoxiaoNeural")

    @staticmethod
    def _build_prompt(topic: str, language: str, turn_count: int) -> str:
        template = PROMPT_TEMPLATE_EN if language == "en" else PROMPT_TEMPLATE_ZH
        return template.format(topic=topic, turn_count=turn_count)

    @staticmethod
    def _build_memory_context(memories: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for idx, memory in enumerate(memories[:5], start=1):
            content = str(memory.get("content", "")).strip()
            if not content:
                continue
            lines.append(f"{idx}. {content[:320]}")
        return "\n".join(lines)

    @staticmethod
    def _build_script_memory_entry(
        *,
        topic: str,
        language: str,
        script_lines: list[dict[str, str]],
    ) -> str:
        preview = " ".join(
            f"{line['role']}: {line['text'][:90]}"
            for line in script_lines[:4]
            if line.get("text")
        )
        if language == "en":
            return (
                f"Echo podcast draft created. Topic: {topic}. "
                f"Language: English. Key dialogue preview: {preview}"
            ).strip()
        return (
            f"Echo 播客草稿已生成。主题：{topic}。"
            f"语言：中文。关键对话预览：{preview}"
        ).strip()



    @staticmethod
    def _safe_filename(prefix: str = "audio_overview") -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}.mp3"

    def _init_db(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS podcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT,
                    language TEXT DEFAULT 'zh',
                    audio_path TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS podcast_scripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    podcast_id INTEGER,
                    line_index INTEGER,
                    role TEXT,
                    content TEXT,
                    FOREIGN KEY(podcast_id) REFERENCES podcasts(id)
                )
                """
            )
            conn.commit()



    def list_podcasts(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, topic, language, audio_path, created_at, updated_at
                FROM podcasts
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            )
            rows = cursor.fetchall()

        return [
            {
                "id": row["id"],
                "topic": row["topic"],
                "language": row["language"],
                "audio_path": row["audio_path"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def get_script(self, podcast_id: int) -> list[dict[str, str]]:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT role, content
                FROM podcast_scripts
                WHERE podcast_id = ?
                ORDER BY line_index ASC
                """,
                (podcast_id,),
            )
            rows = cursor.fetchall()
        return [{"role": row["role"], "text": row["content"]} for row in rows]

    def get_podcast(self, podcast_id: int, include_script: bool = True) -> dict[str, Any] | None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, topic, language, audio_path, created_at, updated_at
                FROM podcasts
                WHERE id = ?
                """,
                (podcast_id,),
            )
            row = cursor.fetchone()
        if row is None:
            return None

        data = {
            "id": row["id"],
            "topic": row["topic"],
            "language": row["language"],
            "audio_path": row["audio_path"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if include_script:
            data["script_lines"] = self.get_script(podcast_id)
        return data

    def get_latest_podcast(self, include_script: bool = True) -> dict[str, Any] | None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id
                FROM podcasts
                ORDER BY updated_at DESC
                LIMIT 1
                """
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return self.get_podcast(int(row["id"]), include_script=include_script)

    def create_podcast(
        self,
        *,
        topic: str,
        language: str = "zh",
        audio_path: str | None = None,
        script_lines: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        clean_topic = topic.strip()
        if not clean_topic:
            raise ValueError("topic is required.")

        clean_language = language.strip() or "zh"
        clean_audio_path = (audio_path or "").strip() or None
        normalized_script = normalize_script_lines(script_lines or [])

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO podcasts (topic, language, audio_path) VALUES (?, ?, ?)",
                (clean_topic, clean_language, clean_audio_path),
            )
            podcast_id = int(cursor.lastrowid)

            if normalized_script:
                for idx, line in enumerate(normalized_script):
                    cursor.execute(
                        """
                        INSERT INTO podcast_scripts (podcast_id, line_index, role, content)
                        VALUES (?, ?, ?, ?)
                        """,
                        (podcast_id, idx, line["role"], line["text"]),
                    )
            conn.commit()
        result = self.get_podcast(podcast_id, include_script=True)
        if result is None:
            raise RuntimeError("Failed to load created podcast.")
        return result

    def save_script(self, podcast_id: int, script_lines: list[dict[str, Any]]) -> list[dict[str, str]]:
        normalized_script = normalize_script_lines(script_lines)
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM podcasts WHERE id = ?", (podcast_id,))
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"podcast not found: {podcast_id}")

            cursor.execute("DELETE FROM podcast_scripts WHERE podcast_id = ?", (podcast_id,))
            for idx, line in enumerate(normalized_script):
                cursor.execute(
                    """
                    INSERT INTO podcast_scripts (podcast_id, line_index, role, content)
                    VALUES (?, ?, ?, ?)
                    """,
                    (podcast_id, idx, line["role"], line["text"]),
                )
            cursor.execute(
                "UPDATE podcasts SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (podcast_id,),
            )
            conn.commit()
        return normalized_script

    def update_podcast(
        self,
        podcast_id: int,
        *,
        topic: str | None = None,
        language: str | None = None,
        audio_path: str | None = None,
        script_lines: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        updates: list[str] = []
        params: list[Any] = []

        if topic is not None:
            clean_topic = topic.strip()
            if not clean_topic:
                raise ValueError("topic cannot be empty.")
            updates.append("topic = ?")
            params.append(clean_topic)

        if language is not None:
            clean_language = language.strip() or "zh"
            updates.append("language = ?")
            params.append(clean_language)

        if audio_path is not None:
            updates.append("audio_path = ?")
            params.append(audio_path.strip() or None)

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM podcasts WHERE id = ?", (podcast_id,))
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"podcast not found: {podcast_id}")

            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(podcast_id)
                cursor.execute(f"UPDATE podcasts SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()

        if script_lines is not None:
            self.save_script(podcast_id, script_lines)

        result = self.get_podcast(podcast_id, include_script=True)
        if result is None:
            raise RuntimeError("Failed to load updated podcast.")
        return result

    def delete_podcast(self, podcast_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, audio_path FROM podcasts WHERE id = ?", (podcast_id,))
            row = cursor.fetchone()
            if row is None:
                return False

            cursor.execute("DELETE FROM podcast_scripts WHERE podcast_id = ?", (podcast_id,))
            cursor.execute("DELETE FROM podcasts WHERE id = ?", (podcast_id,))
            conn.commit()
        # The DB rows are gone — the audio file would otherwise be orphaned.
        self._unlink_managed_audio(row["audio_path"])
        return True

    async def generate_script(
        self,
        *,
        topic: str,
        language: str = "zh",
        turn_count: int = 10,
        provider: str = "DashScope",
        model: str | None = None,
        request_headers: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_topic = topic.strip()
        if not clean_topic:
            raise ValueError("topic is required.")

        clean_language = self._clean_language(language)
        safe_turn_count = max(2, min(int(turn_count), 40))
        prompt = self._build_prompt(clean_topic, clean_language, safe_turn_count)
        clean_provider = str(provider or "DashScope").strip() or "DashScope"
        clean_model = str(model or "").strip() or None
        memories_retrieved = 0
        memory_saved = False

        evermem_config = EverMemConfig()
        if request_headers:
            evermem_config.update_from_headers(request_headers)
        evermem_service = evermem_config.get_service()
        memory_scope = evermem_config.memory_scope

        system_prompt = (
            "You write podcast scripts and must strictly follow the required output format "
            "with one dialogue line per row."
        )
        if evermem_service and not evermem_service.should_skip_memory(clean_topic):
            try:
                memories = await evermem_service.search_memories(
                    query=clean_topic,
                    user_id=memory_scope,
                    min_score=0.3,
                )
                memory_context = self._build_memory_context(memories)
                if memory_context:
                    memories_retrieved = len(memories[:5])
                    system_prompt += (
                        "\n\nRelevant long-term memories for this user. Use them only when they help make "
                        f"the podcast more grounded and personalized.\n{memory_context}"
                    )
            except Exception:
                logger.exception("Audio overview memory retrieval failed")

        completion = await self.llm_service.chat_completion(
            provider=clean_provider,
            model=clean_model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=max(1200, safe_turn_count * 220),
        )

        reply = str(completion.get("reply", "")).strip()
        script_lines = parse_script_with_fallback(reply)
        normalized = normalize_script_lines(script_lines)
        if len(normalized) < 2:
            raise RuntimeError("Generated script is too short or cannot be parsed.")

        if evermem_service:
            try:
                saved = await evermem_service.add_memory(
                    content=self._build_script_memory_entry(
                        topic=clean_topic,
                        language=clean_language,
                        script_lines=normalized,
                    ),
                    user_id=memory_scope,
                    sender=f"{memory_scope}_podcast",
                    sender_name="Echo Podcast",
                )
                memory_saved = saved is not None
            except Exception:
                logger.exception("Audio overview memory save failed")

        return {
            "topic": clean_topic,
            "language": clean_language,
            "turn_count": safe_turn_count,
            "provider": str(completion.get("provider", clean_provider)),
            "model": str(completion.get("model", clean_model or "")),
            "script_lines": normalized,
            "raw_reply": reply,
            "memories_retrieved": memories_retrieved,
            "memory_saved": memory_saved,
        }

    @staticmethod
    def _merge_with_concat(segment_paths: list[Path], output_path: Path) -> dict[str, Any]:
        if not segment_paths:
            raise ValueError("No segment files to merge.")
        if len(segment_paths) == 1:
            shutil.copyfile(segment_paths[0], output_path)
            return {"merge_strategy": "concat", "gap_ms_applied": 0}

        with output_path.open("wb") as target:
            for segment in segment_paths:
                with segment.open("rb") as source:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
        return {"merge_strategy": "concat", "gap_ms_applied": 0}

    @staticmethod
    def _merge_with_pydub(
        segment_paths: list[Path],
        output_path: Path,
        *,
        gap_ms: int,
    ) -> dict[str, Any]:
        from pydub import AudioSegment  # type: ignore

        combined: AudioSegment | None = None
        silence = AudioSegment.silent(duration=max(0, gap_ms))
        for idx, segment in enumerate(segment_paths):
            audio = AudioSegment.from_file(str(segment))
            if combined is None:
                combined = audio
                continue
            if idx > 0 and gap_ms > 0:
                combined += silence
            combined += audio

        if combined is None:
            raise RuntimeError("Failed to load audio segments with pydub.")
        combined.export(str(output_path), format="mp3", bitrate="192k")
        return {"merge_strategy": "pydub", "gap_ms_applied": max(0, gap_ms)}

    @staticmethod
    def _merge_with_ffmpeg(segment_paths: list[Path], output_path: Path) -> dict[str, Any]:
        list_file: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".txt",
                delete=False,
            ) as handle:
                list_file = Path(handle.name)
                for segment in segment_paths:
                    escaped = str(segment).replace("'", "'\\''")
                    handle.write(f"file '{escaped}'\n")

            command = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(output_path),
            ]
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()[-400:]
                raise AudioOverviewServiceError(
                    code="AUDIO_MERGE_FFMPEG_FAILED",
                    message="ffmpeg merge failed.",
                    meta={"returncode": result.returncode, "stderr_tail": detail},
                )
            return {"merge_strategy": "ffmpeg", "gap_ms_applied": 0}
        finally:
            if list_file is not None and list_file.exists():
                list_file.unlink(missing_ok=True)

    def _merge_audio_files(
        self,
        segment_paths: list[Path],
        output_path: Path,
        *,
        gap_ms: int = 250,
        strategy: str = "auto",
    ) -> dict[str, Any]:
        if not segment_paths:
            raise ValueError("No segment files to merge.")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        safe_gap = max(0, min(int(gap_ms), 3000))
        selected = str(strategy or "auto").strip().lower() or "auto"
        if selected not in SUPPORTED_MERGE_STRATEGIES:
            raise AudioOverviewServiceError(
                code="AUDIO_MERGE_STRATEGY_INVALID",
                message=f"Unsupported merge strategy: {selected}",
                meta={"strategy": selected},
            )

        if selected == "pydub":
            try:
                return self._merge_with_pydub(segment_paths, output_path, gap_ms=safe_gap)
            except Exception as exc:
                raise AudioOverviewServiceError(
                    code="AUDIO_MERGE_PYDUB_FAILED",
                    message="pydub merge failed.",
                    meta={"gap_ms": safe_gap, "reason": str(exc)[:400]},
                ) from exc
        if selected == "ffmpeg":
            return self._merge_with_ffmpeg(segment_paths, output_path)
        if selected == "concat":
            return self._merge_with_concat(segment_paths, output_path)

        failures: list[dict[str, str]] = []
        try:
            return self._merge_with_pydub(segment_paths, output_path, gap_ms=safe_gap)
        except Exception as exc:
            failures.append({"strategy": "pydub", "reason": str(exc)[:280]})
            try:
                return self._merge_with_ffmpeg(segment_paths, output_path)
            except Exception as ffmpeg_exc:
                failures.append({"strategy": "ffmpeg", "reason": str(ffmpeg_exc)[:280]})
                try:
                    return self._merge_with_concat(segment_paths, output_path)
                except Exception as concat_exc:
                    failures.append({"strategy": "concat", "reason": str(concat_exc)[:280]})
                    raise AudioOverviewServiceError(
                        code="AUDIO_MERGE_ALL_FAILED",
                        message="All audio merge strategies failed.",
                        meta={"failures": failures},
                    ) from concat_exc

    def _create_intro_music_file(
        self,
        *,
        style: str,
        duration_ms: int,
    ) -> Path:
        try:
            from pydub import AudioSegment  # type: ignore
            from pydub.generators import Sine  # type: ignore
        except Exception as exc:
            raise AudioOverviewServiceError(
                code="AUDIO_INTRO_MUSIC_UNAVAILABLE",
                message="Intro music generation requires pydub and an audio backend.",
                meta={"reason": str(exc)[:400]},
            ) from exc

        selected_style = str(style or "warm").strip().lower() or "warm"
        if selected_style not in SUPPORTED_INTRO_MUSIC_STYLES:
            selected_style = "warm"
        safe_duration_ms = max(800, min(int(duration_ms), 8000))
        style_tones = {
            "warm": (261.63, 329.63, 392.00),
            "bright": (329.63, 493.88, 659.25),
            "calm": (220.00, 277.18, 329.63),
        }

        bed = AudioSegment.silent(duration=safe_duration_ms)
        for idx, frequency in enumerate(style_tones[selected_style]):
            tone = Sine(frequency).to_audio_segment(duration=safe_duration_ms)
            bed = bed.overlay(tone.apply_gain(-19 - idx * 3))
        intro = (
            bed.fade_in(min(450, safe_duration_ms // 4))
            .fade_out(min(900, safe_duration_ms // 3))
            .set_frame_rate(44100)
            .set_channels(2)
        )

        output_path = self.output_dir / self._safe_filename(prefix="podcast_intro")
        try:
            intro.export(str(output_path), format="mp3", bitrate="192k")
        except Exception as exc:
            raise AudioOverviewServiceError(
                code="AUDIO_INTRO_MUSIC_EXPORT_FAILED",
                message="Intro music export failed.",
                meta={
                    "style": selected_style,
                    "duration_ms": safe_duration_ms,
                    "reason": str(exc)[:400],
                },
            ) from exc
        return output_path

    async def synthesize_podcast_audio(
        self,
        podcast_id: int,
        *,
        voice_a: str | None = None,
        voice_b: str | None = None,
        rate: str = "+0%",
        language: str | None = None,
        gap_ms: int = 250,
        merge_strategy: str = "auto",
        intro_music: bool = False,
        intro_music_style: str = "warm",
        intro_music_duration_ms: int = 2500,
    ) -> dict[str, Any]:
        podcast = self.get_podcast(podcast_id, include_script=True)
        if podcast is None:
            raise ValueError(f"podcast not found: {podcast_id}")

        script_lines = normalize_script_lines(
            list(podcast.get("script_lines", []))
        )
        if len(script_lines) < 2:
            raise ValueError("podcast script is empty or too short.")

        resolved_language = self._clean_language(
            language or str(podcast.get("language", "zh"))
        )
        default_a, default_b = self._default_voice_pair(resolved_language)
        resolved_voice_a = str(voice_a or "").strip() or default_a
        resolved_voice_b = str(voice_b or "").strip() or default_b
        resolved_rate = str(rate or "").strip() or "+0%"
        resolved_gap_ms = max(0, min(int(gap_ms), 3000))
        resolved_merge_strategy = str(merge_strategy or "auto").strip().lower() or "auto"
        resolved_intro_music = bool(intro_music)
        resolved_intro_style = str(intro_music_style or "warm").strip().lower() or "warm"
        if resolved_intro_style not in SUPPORTED_INTRO_MUSIC_STYLES:
            resolved_intro_style = "warm"
        resolved_intro_duration_ms = max(800, min(int(intro_music_duration_ms), 8000))

        segment_paths: list[Path] = []
        cache_hits = 0
        intro_path: Path | None = None
        if resolved_intro_music:
            intro_path = self._create_intro_music_file(
                style=resolved_intro_style,
                duration_ms=resolved_intro_duration_ms,
            )
            segment_paths.append(intro_path)
        for idx, line in enumerate(script_lines):
            selected_voice = resolved_voice_a if line["role"] == "A" else resolved_voice_b
            try:
                file_path, _, cache_hit = await self.tts_service.generate_audio(
                    text=line["text"],
                    voice=selected_voice,
                    rate=resolved_rate,
                )
            except Exception as exc:
                logger.exception(
                    "Audio overview segment synthesis failed",
                    extra={
                        "podcast_id": podcast_id,
                        "line_index": idx,
                        "line_role": line["role"],
                    },
                )
                raise AudioOverviewServiceError(
                    code="AUDIO_SEGMENT_SYNTHESIS_FAILED",
                    message="Segment TTS generation failed.",
                    meta={
                        "podcast_id": podcast_id,
                        "line_index": idx,
                        "line_role": line["role"],
                        "voice": selected_voice,
                        "reason": str(exc)[:400],
                    },
                ) from exc
            segment_paths.append(Path(file_path))
            if cache_hit:
                cache_hits += 1

        output_name = self._safe_filename(prefix=f"audio_overview_{podcast_id}")
        output_path = self.output_dir / output_name
        try:
            # _merge_audio_files 内部会跑同步的 ffmpeg subprocess / pydub 解码编码，
            # 放到线程池里执行，避免在 async 合成流程中阻塞事件循环。
            merge_meta = await asyncio.to_thread(
                self._merge_audio_files,
                segment_paths,
                output_path,
                gap_ms=resolved_gap_ms,
                strategy=resolved_merge_strategy,
            )
        except AudioOverviewServiceError:
            logger.exception(
                "Audio overview merge failed",
                extra={
                    "podcast_id": podcast_id,
                    "merge_strategy": resolved_merge_strategy,
                    "gap_ms": resolved_gap_ms,
                },
            )
            raise
        except Exception as exc:
            logger.exception(
                "Audio overview merge failed with unexpected error",
                extra={
                    "podcast_id": podcast_id,
                    "merge_strategy": resolved_merge_strategy,
                    "gap_ms": resolved_gap_ms,
                },
            )
            raise AudioOverviewServiceError(
                code="AUDIO_MERGE_UNKNOWN_ERROR",
                message="Audio merge failed with unknown error.",
                meta={"reason": str(exc)[:400]},
            ) from exc
        previous_audio_path = str(podcast.get("audio_path") or "")
        self.update_podcast(podcast_id, audio_path=str(output_path))
        # The previous take is now unreferenced — remove it so repeated
        # synthesis doesn't accumulate multi-MB files in APPDATA.
        if previous_audio_path and previous_audio_path != str(output_path):
            self._unlink_managed_audio(previous_audio_path)
        await self._maybe_cleanup_old_files()

        return {
            "podcast_id": podcast_id,
            "audio_path": str(output_path),
            "line_count": len(script_lines),
            "voice_a": resolved_voice_a,
            "voice_b": resolved_voice_b,
            "rate": resolved_rate,
            "cache_hits": cache_hits,
            "gap_ms": resolved_gap_ms,
            "gap_ms_applied": int(merge_meta.get("gap_ms_applied", 0)),
            "merge_strategy": str(merge_meta.get("merge_strategy", "concat")),
            "intro_music": resolved_intro_music,
            "intro_music_style": resolved_intro_style if resolved_intro_music else "off",
            "intro_music_duration_ms": resolved_intro_duration_ms if resolved_intro_music else 0,
            "intro_music_path": str(intro_path) if intro_path is not None else "",
        }
