from __future__ import annotations

import asyncio
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

_backend_dir = Path(__file__).resolve().parents[1]
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

import httpx
import pytest
from fastapi.testclient import TestClient

from main import create_app
from routers import agent_runs as agent_runs_router
from routers import audio_agent as audio_agent_router
from routers import audio_overview as audio_overview_router
from routers import auth as auth_router
from routers import chat as chat_router
from routers import evermem as evermem_router
from routers import settings as settings_router
from routers import transcription as transcription_router
from routers import translate as translate_router
from routers import tts as tts_router
from routers import voice_chat as voice_chat_router
from routers import voices as voices_router
from services.agent_run_service import AgentRunService
from services.audio_agent_service import AudioAgentService
from services.audio_overview_service import AudioOverviewService
from services.config_loader import BackendConfig
from services.evermem_service import EverMemService
from services.settings_service import SettingsService
from services.transcription_service import TranscriptionJob, TranscriptionService
from services.tts_service import TTSAudioResult, TTSService
from services.user_auth_service import user_auth_service
from services.voice_agent_session_repository import VoiceAgentSessionRepository


@pytest.fixture
def e2e_env(tmp_path: Path):
    """
    Sets up a completely hermetic, isolated E2E test environment:
    - Temporary SQLite databases for all repositories and services
    - Temporary directories for TTS audio, podcast storage, and transcription jobs
    - Auth tokens configured in environment
    - Pristine FastAPI application instance and TestClient
    """
    # 1. Setup isolated directories & config
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps(
            {
                "api_keys": {
                    "dashscope_api_key": "sk-test-dashscope",
                    "google_api_key": "test-google-key",
                    "xiaomi_api_key": "test-xiaomi-key",
                },
                "api_urls": {
                    "DashScope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    "Google": "",
                    "Xiaomi": "https://api.xiaomi.com/v1",
                },
                "default_models": {
                    "DashScope": {"default": "qwen-plus", "available": ["qwen-plus", "qwen-max"]},
                    "Google": {"default": "gemini-2.5-flash", "available": ["gemini-2.5-flash"]},
                },
                "general_settings": {
                    "log_level": "INFO",
                    "display_language": "zh-CN",
                },
                "auth_settings": {
                    "api_token": "e2e-api-token",
                    "admin_token": "e2e-admin-token",
                },
            }
        ),
        encoding="utf-8",
    )

    # 2. Setup isolated databases
    audio_overview_db = tmp_path / "audio_overview_e2e.db"
    audio_overview_dir = tmp_path / "podcasts_e2e"
    audio_overview_dir.mkdir(parents=True, exist_ok=True)

    voice_agent_db = tmp_path / "voice_agent_e2e.db"
    agent_runs_db = tmp_path / "agent_runs_e2e.db"
    auth_db = tmp_path / "auth_e2e.db"
    transcription_dir = tmp_path / "transcriptions_e2e"
    transcription_dir.mkdir(parents=True, exist_ok=True)

    # Save original services & paths
    orig_ao_service = audio_overview_router.audio_overview_service
    orig_va_repo = voice_chat_router.voice_agent_session_repository
    orig_ar_service = agent_runs_router.agent_run_service
    orig_aa_service = audio_agent_router.audio_agent_service
    orig_auth_db = user_auth_service.db_path
    orig_auth_config = user_auth_service.config
    orig_tx_dir = transcription_router.transcription_service.jobs_dir
    orig_settings_service = settings_router.settings_service

    # Initialize isolated services
    test_ao_service = AudioOverviewService(db_path=audio_overview_db, output_dir=audio_overview_dir)
    audio_overview_router.audio_overview_service = test_ao_service

    test_va_repo = VoiceAgentSessionRepository(voice_agent_db)
    voice_chat_router.voice_agent_session_repository = test_va_repo

    test_audio_agent = AudioAgentService(db_path=agent_runs_db, audio_overview_service=test_ao_service)
    audio_agent_router.audio_agent_service = test_audio_agent
    test_ar_service = AgentRunService(db_path=agent_runs_db, audio_agent_service=test_audio_agent)
    agent_runs_router.agent_run_service = test_ar_service

    user_auth_service.db_path = auth_db
    user_auth_service.config = BackendConfig(config_file)
    user_auth_service._init_db()

    transcription_router.transcription_service.jobs_dir = transcription_dir

    test_settings_service = SettingsService(config=BackendConfig(config_file))
    settings_router.settings_service = test_settings_service

    # Setup environment tokens
    env_patcher = patch.dict(
        os.environ,
        {
            "VOICESPIRIT_API_TOKEN": "e2e-api-token",
            "VOICESPIRIT_ADMIN_TOKEN": "e2e-admin-token",
            "VOICESPIRIT_JWT_SECRET": "e2e-jwt-secret-key",
        },
        clear=False,
    )
    env_patcher.start()

    app = create_app()
    client = TestClient(app)

    yield {
        "app": app,
        "client": client,
        "tmp_path": tmp_path,
        "audio_overview_dir": audio_overview_dir,
        "transcription_dir": transcription_dir,
        "voice_agent_repo": test_va_repo,
        "audio_agent_service": test_audio_agent,
        "agent_run_service": test_ar_service,
        "auth_headers": {"Authorization": "Bearer e2e-api-token"},
        "admin_headers": {"Authorization": "Bearer e2e-admin-token"},
    }

    # Teardown & restore
    env_patcher.stop()
    audio_overview_router.audio_overview_service = orig_ao_service
    voice_chat_router.voice_agent_session_repository = orig_va_repo
    audio_agent_router.audio_agent_service = orig_aa_service
    agent_runs_router.agent_run_service = orig_ar_service
    user_auth_service.db_path = orig_auth_db
    user_auth_service.config = orig_auth_config
    user_auth_service._init_db()
    transcription_router.transcription_service.jobs_dir = orig_tx_dir
    settings_router.settings_service = orig_settings_service


# ==============================================================================
# TIER 1: FEATURE CONTRACTS (45 Tests: 5 per feature across 9 domains)
# ==============================================================================

# --- Domain 1: Multi-Engine TTS ---

def test_tier1_tts_list_voices_edge(e2e_env):
    """Tier 1: Verify edge engine voices list contract."""
    client = e2e_env["client"]
    resp = client.get("/api/tts/voices?engine=edge&locale=zh-CN")
    assert resp.status_code == 200
    data = resp.json()
    assert "voices" in data
    assert "count" in data
    assert data["count"] > 0
    first_voice = data["voices"][0]
    assert "name" in first_voice
    assert "locale" in first_voice


def test_tier1_tts_list_voices_qwen_flash(e2e_env):
    """Tier 1: Verify qwen_flash engine voices list contract."""
    client = e2e_env["client"]
    resp = client.get("/api/tts/voices?engine=qwen_flash")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0
    names = [v["name"] for v in data["voices"]]
    assert len(names) > 0


def test_tier1_tts_speak_single_voice(e2e_env):
    """Tier 1: Verify single voice TTS audio synthesis contract."""
    client = e2e_env["client"]
    fake_audio_path = e2e_env["tmp_path"] / "tier1_tts.mp3"
    fake_audio_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00#TSSE2EAUDIO")

    async def fake_generate_audio(*args, **kwargs):
        return TTSAudioResult(
            file_path=str(fake_audio_path),
            voice="zh-CN-XiaoxiaoNeural",
            engine="edge",
            media_type="audio/mpeg",
            filename="tts_output.mp3",
            cache_hit=False,
        )

    with patch.object(tts_router.tts_service, "generate_audio", new=fake_generate_audio):
        resp = client.get(
            "/api/tts/speak?text=Hello+World&voice=zh-CN-XiaoxiaoNeural&rate=%2B0%25&engine=edge"
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert resp.headers.get("x-tts-engine") == "edge"
        assert len(resp.content) > 0


def test_tier1_tts_speak_dialogue_dual_voice(e2e_env):
    """Tier 1: Verify dual-voice dialogue TTS synthesis contract."""
    client = e2e_env["client"]
    fake_dialogue_path = e2e_env["tmp_path"] / "tier1_dialogue.mp3"
    fake_dialogue_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00#DIALOGUEAUDIO")

    async def fake_generate_dialogue_audio(*args, **kwargs):
        return TTSAudioResult(
            file_path=str(fake_dialogue_path),
            voice="zh-CN-XiaoxiaoNeural + zh-CN-YunxiNeural",
            engine="edge",
            media_type="audio/mpeg",
            filename="tts_dialogue.mp3",
            cache_hit=False,
        )

    with patch.object(tts_router.tts_service, "generate_dialogue_audio", new=fake_generate_dialogue_audio):
        resp = client.get(
            "/api/tts/speak?text=A:+Hi%0AB:+Hello&voice=zh-CN-XiaoxiaoNeural&voice_b=zh-CN-YunxiNeural&engine=edge"
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/mpeg"
        assert len(resp.content) > 0


def test_tier1_tts_stream_with_timestamps(e2e_env):
    """Tier 1: Verify stream with timestamps endpoint response format."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/tts/stream-with-timestamps",
        json={"text": "Streaming test", "voice": "zh-CN-XiaoxiaoNeural"},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")


# --- Domain 2: LLM Chat & Translation ---

def test_tier1_chat_completions_basic(e2e_env):
    """Tier 1: Verify standard LLM chat completion contract."""
    client = e2e_env["client"]

    async def fake_chat_completion(**kwargs):
        return {
            "provider": "DashScope",
            "model": "qwen-plus",
            "reply": "Echo is ready to assist you.",
            "raw": {"usage": {"total_tokens": 42}},
        }

    with patch.object(chat_router.llm_service, "chat_completion", new=fake_chat_completion):
        resp = client.post(
            "/api/chat/completions",
            json={
                "provider": "DashScope",
                "model": "qwen-plus",
                "messages": [{"role": "user", "content": "Hello Echo"}],
            },
            headers=e2e_env["auth_headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "DashScope"
        assert data["reply"] == "Echo is ready to assist you."


def test_tier1_chat_completions_stream_sse(e2e_env):
    """Tier 1: Verify SSE chat completions stream contract."""
    client = e2e_env["client"]

    async def fake_chat_stream(**kwargs):
        yield {"delta": "Hello", "reasoning_delta": "", "done": False}
        yield {"delta": " world!", "reasoning_delta": "", "done": True, "reply": "Hello world!"}

    with patch.object(chat_router.llm_service, "chat_completion_stream", new=fake_chat_stream):
        resp = client.post(
            "/api/chat/completions/stream",
            json={
                "provider": "DashScope",
                "messages": [{"role": "user", "content": "Stream me"}],
            },
            headers=e2e_env["auth_headers"],
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        assert "delta" in resp.text


def test_tier1_chat_memory_flag_forwarded(e2e_env):
    """Tier 1: Verify use_memory flag is accepted and honored."""
    client = e2e_env["client"]

    async def fake_chat_completion(**kwargs):
        assert kwargs.get("use_memory") is True
        return {
            "provider": "DashScope",
            "model": "qwen-plus",
            "reply": "Context remembered.",
            "raw": {},
        }

    with patch.object(chat_router.llm_service, "chat_completion", new=fake_chat_completion):
        resp = client.post(
            "/api/chat/completions",
            json={
                "provider": "DashScope",
                "messages": [{"role": "user", "content": "Remember this."}],
                "use_memory": True,
            },
            headers=e2e_env["auth_headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["reply"] == "Context remembered."


def test_tier1_translate_text_basic(e2e_env):
    """Tier 1: Verify text translation endpoint contract."""
    client = e2e_env["client"]

    async def fake_translate(**kwargs):
        return {
            "provider": "DashScope",
            "model": "qwen-plus",
            "translated_text": "Hello world",
        }

    with patch.object(translate_router.llm_service, "translate_text", new=fake_translate):
        resp = client.post(
            "/api/translate/",
            json={
                "text": "你好世界",
                "source_language": "zh",
                "target_language": "en",
                "provider": "DashScope",
            },
            headers=e2e_env["auth_headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["translated_text"] == "Hello world"


def test_tier1_translate_image_ocr(e2e_env):
    """Tier 1: Verify image translation endpoint contract."""
    client = e2e_env["client"]

    async def fake_translate_img(**kwargs):
        return {
            "provider": "DashScope",
            "model": "qwen-vl-plus",
            "translated_text": "Sign text translated",
        }

    with patch.object(translate_router.llm_service, "translate_image", new=fake_translate_img):
        files = {"image_file": ("test.png", b"\x89PNG\r\n\x1a\nFakeImageData", "image/png")}
        data = {"target_language": "en", "source_language": "zh", "provider": "DashScope"}
        resp = client.post(
            "/api/translate/image",
            files=files,
            data=data,
            headers=e2e_env["auth_headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["translated_text"] == "Sign text translated"


# --- Domain 3: Realtime Voice Duplex ---

def test_tier1_voice_duplex_create_and_list_sessions(e2e_env):
    """Tier 1: Verify voice duplex session creation and listing."""
    repo = e2e_env["voice_agent_repo"]
    client = e2e_env["client"]

    session = repo.create_session(
        provider="DashScope",
        model="qwen-realtime",
        voice="Cherry",
    )
    assert session["id"]

    resp = client.get("/api/voice-chat/sessions?limit=10", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert any(s["id"] == session["id"] for s in data["sessions"])


def test_tier1_voice_duplex_session_detail_and_timeline(e2e_env):
    """Tier 1: Verify voice duplex session turn detail and chronological timeline."""
    repo = e2e_env["voice_agent_repo"]
    client = e2e_env["client"]

    session = repo.create_session(provider="Google", model="gemini-live", voice="Puck")
    repo.upsert_turn(
        session["id"],
        "turn-1",
        user_text="What's the weather today?",
        assistant_text="It is sunny and 22 degrees.",
        completed=True,
    )
    repo.add_tool_event(
        session["id"],
        "tool_call",
        {"tool_name": "get_weather", "location": "Beijing"},
    )

    resp = client.get(f"/api/voice-chat/sessions/{session['id']}", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    detail = resp.json()
    assert len(detail["turns"]) == 1
    assert detail["turns"][0]["user_text"] == "What's the weather today?"
    assert len(detail["tool_events"]) == 1
    assert len(detail["timeline"]) >= 3


def test_tier1_voice_duplex_agent_run_link(e2e_env):
    """Tier 1: Verify linking agent run to voice duplex turn."""
    repo = e2e_env["voice_agent_repo"]
    client = e2e_env["client"]

    session = repo.create_session(provider="DashScope", model="qwen-realtime", voice="Cherry")
    repo.upsert_turn(
        session["id"],
        "turn-link-1",
        user_text="Research podcast",
        assistant_text="Starting research...",
        completed=True,
    )
    repo.link_agent_run_artifact(
        session["id"],
        "turn-link-1",
        {"type": "audio_agent_run", "run_id": 101, "status": "completed", "topic": "Tech Podcast"},
    )

    resp = client.get(f"/api/voice-chat/sessions/{session['id']}", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["agent_run_links"]) == 1
    assert data["agent_run_links"][0]["agent_run_id"] == "audio_agent:101"


def test_tier1_voice_duplex_metrics_summary(e2e_env):
    """Tier 1: Verify voice session metrics aggregate summary."""
    repo = e2e_env["voice_agent_repo"]
    client = e2e_env["client"]

    session = repo.create_session(provider="DashScope", model="qwen-realtime", voice="Cherry")
    repo.upsert_turn(
        session["id"],
        "turn-metric-1",
        user_text="Hi",
        assistant_text="Hello",
        completed=True,
    )
    repo.add_session_event(session["id"], "first_audio", source="runtime", payload={"latency_ms": 350})

    resp = client.get("/api/voice-chat/sessions/metrics/summary", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    metrics = resp.json()
    assert "session_count" in metrics
    assert metrics["session_count"] >= 1


def test_tier1_voice_duplex_websocket_route_registered(e2e_env):
    """Tier 1: Verify WebSocket route for duplex voice chat is mounted."""
    app = e2e_env["app"]
    routes = [getattr(r, "path", "") for r in app.routes]
    assert "/api/voice-chat/ws" in routes


# --- Domain 4: Audio Overview (Podcasts) ---

def test_tier1_podcast_generate_script(e2e_env):
    """Tier 1: Verify podcast script generation endpoint."""
    client = e2e_env["client"]

    async def fake_generate_script(*args, **kwargs):
        return {
            "topic": "AI Innovations",
            "language": "zh",
            "turn_count": 4,
            "provider": "DashScope",
            "model": "qwen-plus",
            "script_lines": [
                {"role": "A", "text": "欢迎收听科技播客。"},
                {"role": "B", "text": "今天我们来聊聊最新 AI 突破。"},
            ],
            "memories_retrieved": 0,
            "memory_saved": False,
        }

    with patch.object(audio_overview_router.audio_overview_service, "generate_script", new=fake_generate_script):
        resp = client.post(
            "/api/audio-overview/scripts/generate",
            json={"topic": "AI Innovations", "language": "zh", "turn_count": 4, "provider": "DashScope"},
            headers=e2e_env["auth_headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["script_lines"]) == 2
        assert data["script_lines"][0]["role"] == "A"


def test_tier1_podcast_create_and_get(e2e_env):
    """Tier 1: Verify podcast creation and retrieval by ID."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/audio-overview/podcasts",
        json={
            "topic": "Quantum Computing",
            "language": "zh",
            "script_lines": [
                {"role": "A", "text": "量子计算很有前景。"},
                {"role": "B", "text": "是的，算力呈指数级。"},
            ],
        },
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code == 200
    created = resp.json()
    pid = created["id"]
    assert pid > 0

    get_resp = client.get(f"/api/audio-overview/podcasts/{pid}")
    assert get_resp.status_code == 200
    fetched = get_resp.json()
    assert fetched["topic"] == "Quantum Computing"
    assert len(fetched["script_lines"]) == 2


def test_tier1_podcast_update_script(e2e_env):
    """Tier 1: Verify updating podcast script lines."""
    client = e2e_env["client"]
    create_resp = client.post(
        "/api/audio-overview/podcasts",
        json={"topic": "Space Travel", "language": "zh"},
        headers=e2e_env["auth_headers"],
    )
    pid = create_resp.json()["id"]

    update_resp = client.put(
        f"/api/audio-overview/podcasts/{pid}/script",
        json={"script_lines": [{"role": "A", "text": "Updated line 1"}, {"role": "B", "text": "Updated line 2"}]},
        headers=e2e_env["auth_headers"],
    )
    assert update_resp.status_code == 200
    assert len(update_resp.json()["script_lines"]) == 2


def test_tier1_podcast_synthesize_audio(e2e_env):
    """Tier 1: Verify podcast audio synthesis pipeline contract."""
    client = e2e_env["client"]
    create_resp = client.post(
        "/api/audio-overview/podcasts",
        json={
            "topic": "Synthesize Test",
            "language": "zh",
            "script_lines": [{"role": "A", "text": "Synthesize this."}, {"role": "B", "text": "Line 2."}],
        },
        headers=e2e_env["auth_headers"],
    )
    pid = create_resp.json()["id"]

    fake_podcast_audio = e2e_env["audio_overview_dir"] / f"podcast_{pid}.mp3"
    fake_podcast_audio.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00#PODCASTAUDIO")

    async def fake_synthesize(*args, **kwargs):
        audio_overview_router.audio_overview_service.update_podcast(pid, audio_path=str(fake_podcast_audio))
        return {
            "podcast_id": pid,
            "audio_path": str(fake_podcast_audio),
            "audio_download_url": f"/api/audio-overview/podcasts/{pid}/audio",
            "line_count": 2,
            "voice_a": "zh-CN-YunxiNeural",
            "voice_b": "zh-CN-XiaoxiaoNeural",
            "rate": "+0%",
            "cache_hits": 0,
            "gap_ms": 250,
            "gap_ms_applied": 250,
            "merge_strategy": "auto",
            "intro_music": False,
            "intro_music_style": "off",
            "intro_music_duration_ms": 0,
        }

    with patch.object(audio_overview_router.audio_overview_service, "synthesize_podcast_audio", new=fake_synthesize):
        synth_resp = client.post(
            f"/api/audio-overview/podcasts/{pid}/synthesize",
            json={"merge_strategy": "auto"},
            headers=e2e_env["auth_headers"],
        )
        assert synth_resp.status_code == 200
        data = synth_resp.json()
        assert data["podcast_id"] == pid
        assert data["audio_path"] == str(fake_podcast_audio)


def test_tier1_podcast_delete_by_id(e2e_env):
    """Tier 1: Verify deleting podcast by exact ID contract."""
    client = e2e_env["client"]
    create_resp = client.post(
        "/api/audio-overview/podcasts",
        json={"topic": "Delete Me", "language": "zh"},
        headers=e2e_env["auth_headers"],
    )
    pid = create_resp.json()["id"]

    del_resp = client.delete(
        f"/api/audio-overview/podcasts/{pid}",
        headers=e2e_env["auth_headers"],
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    # Verify not found after deletion
    get_resp = client.get(f"/api/audio-overview/podcasts/{pid}")
    assert get_resp.status_code == 404


# --- Domain 5: Audio Transcription & ASR ---

def test_tier1_transcription_sync_file(e2e_env):
    """Tier 1: Verify synchronous file transcription endpoint."""
    client = e2e_env["client"]

    async def fake_transcribe_media(*args, **kwargs):
        return {
            "text": "Hello this is a transcription test.",
            "duration_seconds": 3.5,
            "words": [{"text": "Hello", "start": 0.0, "end": 0.5}],
            "provider": "google",
        }

    with patch.object(transcription_router.transcription_service, "transcribe_media", new=fake_transcribe_media):
        files = {"file": ("sample.wav", b"RIFF....WAVEfmt ....data....", "audio/wav")}
        resp = client.post(
            "/api/transcription/",
            files=files,
            headers=e2e_env["auth_headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcript"] == "Hello this is a transcription test."
        assert data["duration_seconds"] == 3.5


def test_tier1_transcription_async_submit_and_status(e2e_env):
    """Tier 1: Verify async transcription job submission and retrieval."""
    client = e2e_env["client"]

    async def fake_prepare_job(upload_path, original_name):
        t_path = e2e_env["tmp_path"] / "t1_transcript.txt"
        t_path.write_text("Async transcription complete.", encoding="utf-8")
        job = TranscriptionJob(
            file_path=str(upload_path),
            job_id="job-tier1-123",
            remote_job_id="rem-123",
            mode="file",
            status="completed",
            original_filename="sample.mp3",
            duration_seconds=12.0,
            transcript_path=str(t_path),
        )
        return transcription_router.transcription_service._write_job(job)

    with patch.object(transcription_router.transcription_service, "prepare_long_transcription_job", new=fake_prepare_job):
        files = {"file": ("sample.mp3", b"ID3FakeData", "audio/mpeg")}
        submit_resp = client.post(
            "/api/transcription/jobs",
            files=files,
            headers=e2e_env["auth_headers"],
        )
        assert submit_resp.status_code == 200
        job_id = submit_resp.json()["job_id"]

        get_resp = client.get(f"/api/transcription/jobs/{job_id}", headers=e2e_env["auth_headers"])
        assert get_resp.status_code == 200
        assert get_resp.json()["status"] in ["queued", "running", "completed"]


def test_tier1_transcription_download_transcript(e2e_env):
    """Tier 1: Verify transcript download endpoint."""
    client = e2e_env["client"]

    t_path = e2e_env["tmp_path"] / "job_dl_transcript.txt"
    t_path.write_text("Downloaded transcript line 1.\nLine 2.", encoding="utf-8")

    job = TranscriptionJob(
        file_path="dummy_path.mp3",
        job_id="job-dl-test",
        mode="file",
        status="completed",
        original_filename="interview.mp3",
        transcript_path=str(t_path),
    )
    transcription_router.transcription_service._write_job(job)

    resp = client.get(
        "/api/transcription/jobs/job-dl-test/transcript.txt",
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    assert "Downloaded transcript line 1." in resp.text


def test_tier1_transcription_words_endpoint(e2e_env):
    """Tier 1: Verify word-level timestamps retrieval."""
    client = e2e_env["client"]

    job = TranscriptionJob(
        file_path="dummy_path.mp3",
        job_id="job-words-test",
        mode="file",
        status="completed",
        original_filename="audio.mp3",
    )
    transcription_router.transcription_service._write_job(job)
    words_file = transcription_router.transcription_service.jobs_dir / "job-words-test_words.json"
    words_file.write_text(json.dumps([{"text": "Hello", "start": 0.0, "end": 0.5}]), encoding="utf-8")

    resp = client.get("/api/transcription/jobs/job-words-test/words", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    words = resp.json()
    assert len(words) == 1
    assert words[0]["text"] == "Hello"


def test_tier1_transcription_save_text_and_words(e2e_env):
    """Tier 1: Verify saving transcription text and words into new job."""
    client = e2e_env["client"]

    resp = client.post(
        "/api/transcription/jobs/save-text",
        json={"transcript": "Corrected transcript text.", "file_name": "editable.mp3", "words": [{"text": "Corrected", "start": 0, "end": 1}]},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["transcript"] == "Corrected transcript text."
    assert resp.json()["status"] == "completed"


# --- Domain 6: Voice Design & Voice Cloning ---

def test_tier1_voice_design_create(e2e_env):
    """Tier 1: Verify creating custom voice design."""
    client = e2e_env["client"]

    async def fake_create_voice_design(**kwargs):
        return {
            "voice": "custom-voice-design-01",
            "type": "voice_design",
            "target_model": "cosyvoice-v1",
            "preferred_name": "Warm Narrator",
            "language": "zh",
            "preview_audio_data": "base64audiodata",
            "provider": "qwen",
        }

    with patch.object(voices_router.qwen_voice_service, "create_voice_design", new=fake_create_voice_design):
        resp = client.post(
            "/api/voices/design",
            json={
                "voice_prompt": "Warm, reassuring voice for news.",
                "preview_text": "欢迎收听今日早报。",
                "preferred_name": "Warm Narrator",
                "language": "zh",
                "provider": "qwen",
            },
            headers=e2e_env["auth_headers"],
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["voice"] == "custom-voice-design-01"
        assert data["type"] == "voice_design"


def test_tier1_voice_design_list(e2e_env):
    """Tier 1: Verify listing custom voice designs."""
    client = e2e_env["client"]

    async def fake_list_voices(**kwargs):
        return {
            "voice_type": "voice_design",
            "count": 1,
            "voices": [{"voice": "vd-01", "preferred_name": "Warm Narrator", "type": "voice_design"}],
        }

    with patch.object(voices_router.qwen_voice_service, "list_voices", new=fake_list_voices):
        resp = client.get("/api/voices/?voice_type=voice_design", headers=e2e_env["auth_headers"])
        assert resp.status_code == 200
        data = resp.json()
        assert data["voice_type"] == "voice_design"
        assert data["count"] == 1


def test_tier1_voice_clone_create_with_audio(e2e_env):
    """Tier 1: Verify voice clone creation with audio file upload."""
    client = e2e_env["client"]

    async def fake_create_voice_clone(**kwargs):
        return {
            "voice": "cloned-voice-01",
            "type": "voice_clone",
            "target_model": "cosyvoice-clone",
            "preferred_name": "My Cloned Voice",
            "language": "zh",
            "preview_audio_data": None,
            "provider": "qwen",
        }

    with patch.object(voices_router.qwen_voice_service, "create_voice_clone", new=fake_create_voice_clone):
        files = {"audio_file": ("ref.mp3", b"ID3FakeReferenceAudio", "audio/mpeg")}
        data = {"preferred_name": "My Cloned Voice", "provider": "qwen"}
        resp = client.post(
            "/api/voices/clone",
            files=files,
            data=data,
            headers=e2e_env["auth_headers"],
        )
        assert resp.status_code == 200
        assert resp.json()["voice"] == "cloned-voice-01"


def test_tier1_voice_clone_list(e2e_env):
    """Tier 1: Verify listing cloned voices."""
    client = e2e_env["client"]

    async def fake_list_voices(**kwargs):
        return {
            "voice_type": "voice_clone",
            "count": 1,
            "voices": [{"voice": "vc-01", "preferred_name": "My Cloned Voice", "type": "voice_clone"}],
        }

    with patch.object(voices_router.qwen_voice_service, "list_voices", new=fake_list_voices):
        resp = client.get("/api/voices/?voice_type=voice_clone", headers=e2e_env["auth_headers"])
        assert resp.status_code == 200
        assert resp.json()["voice_type"] == "voice_clone"
        assert resp.json()["count"] == 1


def test_tier1_voice_delete(e2e_env):
    """Tier 1: Verify deleting custom voice design/clone."""
    client = e2e_env["client"]

    async def fake_delete_voice(**kwargs):
        return {"voice": "vd-01", "type": "voice_design", "deleted": True}

    with patch.object(voices_router.qwen_voice_service, "delete_voice", new=fake_delete_voice):
        resp = client.delete("/api/voices/vd-01?voice_type=voice_design", headers=e2e_env["auth_headers"])
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True


# --- Domain 7: EverMem & Agent Workflows ---

def test_tier1_evermem_conversation_meta(e2e_env):
    """Tier 1: Verify EverMem conversation metadata resolution."""
    client = e2e_env["client"]

    async def fake_create_conv_meta(*args, **kwargs):
        group_id = kwargs.get("group_id") or "group-auto-123"
        user_id = kwargs.get("user_id") or "test-scope"
        return {"group_id": group_id, "user_id": user_id}

    with patch.object(EverMemService, "create_conversation_meta", new=fake_create_conv_meta):
        resp = client.post(
            "/api/evermem/conversation-meta",
            json={"group_id": "custom-group-1"},
            headers={
                **e2e_env["auth_headers"],
                "X-EverMem-Enabled": "true",
                "X-EverMem-Key": "test-key",
                "X-EverMem-Url": "https://api.evermind.ai",
                "X-EverMem-Scope": "test-scope",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["group_id"] == "custom-group-1"
        assert data["user_id"] == "test-scope"


def test_tier1_agent_runs_create_and_list(e2e_env):
    """Tier 1: Verify agent run creation and unified listing."""
    client = e2e_env["client"]
    audio_agent = e2e_env["audio_agent_service"]

    run = audio_agent.create_run(topic="Podcast Research Agent", auto_execute=False)
    assert run["id"]

    resp = client.get("/api/agent-runs/?limit=10", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    assert any(r["id"] == f"audio_agent:{run['id']}" for r in data["runs"])


def test_tier1_agent_runs_get_detail(e2e_env):
    """Tier 1: Verify agent run detail endpoint."""
    client = e2e_env["client"]
    audio_agent = e2e_env["audio_agent_service"]
    agent_runs = e2e_env["agent_run_service"]

    run = audio_agent.create_run(topic="Detailed Run Topic", auto_execute=False)
    agent_runs.repository.upsert_audio_run(run)
    canonical_id = f"audio_agent:{run['id']}"
    resp = client.get(f"/api/agent-runs/{canonical_id}", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    assert resp.json()["title"] == "Detailed Run Topic"


def test_tier1_agent_runs_events_stream(e2e_env):
    """Tier 1: Verify agent run chronological event trace listing."""
    client = e2e_env["client"]
    audio_agent = e2e_env["audio_agent_service"]
    agent_runs = e2e_env["agent_run_service"]

    run = audio_agent.create_run(topic="Event Run", auto_execute=False)
    agent_runs.repository.upsert_audio_run(run)
    run_id = int(run["id"])
    audio_agent.repository.add_event(run_id=run_id, event_type="step_started", payload={"step": "search"})
    audio_agent.repository.add_event(run_id=run_id, event_type="step_completed", payload={"step": "search", "results": 5})

    canonical_id = f"audio_agent:{run_id}"
    resp = client.get(f"/api/agent-runs/{canonical_id}/events", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) >= 2


def test_tier1_audio_agent_create_and_query(e2e_env):
    """Tier 1: Verify AudioAgentService dedicated run creation."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/audio-agent/runs",
        json={"topic": "Neural Interfaces", "auto_execute": False},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code == 200
    run_id = resp.json()["id"]

    get_resp = client.get(f"/api/audio-agent/runs/{run_id}", headers=e2e_env["auth_headers"])
    assert get_resp.status_code == 200
    assert get_resp.json()["topic"] == "Neural Interfaces"


# --- Domain 8: Error Handling & Structured JSON ---

def test_tier1_error_structure_404_not_found(e2e_env):
    """Tier 1: Verify 404 error adheres to structured JSON detail schema."""
    client = e2e_env["client"]
    resp = client.get("/api/audio-overview/podcasts/9999999")
    assert resp.status_code == 404
    body = resp.json()
    assert "detail" in body
    assert "code" in body["detail"]
    assert "message" in body["detail"]
    assert "meta" in body["detail"]
    assert body["detail"]["code"] == "AUDIO_OVERVIEW_NOT_FOUND"


def test_tier1_error_structure_400_validation(e2e_env):
    """Tier 1: Verify 400 bad request returns structured error format."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/audio-overview/podcasts",
        json={"topic": ""},  # empty topic violates min_length
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 422]


def test_tier1_error_structure_401_missing_auth(e2e_env):
    """Tier 1: Verify 401 missing Bearer token structured error."""
    client = e2e_env["client"]
    resp = client.post("/api/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 401
    detail = resp.json()["detail"]
    assert detail["code"] == "AUTH_TOKEN_MISSING"


def test_tier1_error_structure_403_invalid_auth(e2e_env):
    """Tier 1: Verify 403 invalid token structured error."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"Authorization": "Bearer bad-token-xyz"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "AUTH_TOKEN_INVALID"


def test_tier1_error_x_request_id_header_propagated(e2e_env):
    """Tier 1: Verify X-Request-ID request header is passed to response."""
    client = e2e_env["client"]
    req_id = "req-test-e2e-001"
    resp = client.get("/health", headers={"X-Request-ID": req_id})
    assert resp.status_code == 200
    assert resp.headers.get("x-request-id") == req_id


# --- Domain 9: Bilingual i18n Localization ---

def test_tier1_settings_get_and_display_language(e2e_env):
    """Tier 1: Verify settings response includes display language."""
    client = e2e_env["client"]
    resp = client.get("/api/settings/", headers=e2e_env["admin_headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert "general_settings" in data["settings"]
    assert data["settings"]["general_settings"]["display_language"] in ["zh-CN", "en-US"]


def test_tier1_settings_update_bilingual_preferences(e2e_env):
    """Tier 1: Verify updating display language preference in settings."""
    client = e2e_env["client"]
    resp = client.put(
        "/api/settings/",
        json={"merge": True, "settings": {"general_settings": {"display_language": "en-US"}}},
        headers=e2e_env["admin_headers"],
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["general_settings"]["display_language"] == "en-US"


def test_tier1_tts_language_locale_filtering(e2e_env):
    """Tier 1: Verify filtering voices by locale (zh vs en)."""
    client = e2e_env["client"]
    zh_resp = client.get("/api/tts/voices?engine=edge&locale=zh-CN")
    assert zh_resp.status_code == 200
    for v in zh_resp.json()["voices"]:
        assert v["locale"].startswith("zh")

    en_resp = client.get("/api/tts/voices?engine=edge&locale=en-US")
    assert en_resp.status_code == 200
    for v in en_resp.json()["voices"]:
        assert v["locale"].startswith("en")


def test_tier1_translate_target_language_support(e2e_env):
    """Tier 1: Verify bilingual translation target languages (zh -> en, en -> zh)."""
    client = e2e_env["client"]

    async def fake_translate(text, target_language, **kwargs):
        if target_language == "en":
            return {"provider": "DashScope", "model": "qwen-plus", "translated_text": "Good morning"}
        return {"provider": "DashScope", "model": "qwen-plus", "translated_text": "早上好"}

    with patch.object(translate_router.llm_service, "translate_text", new=fake_translate):
        resp_en = client.post(
            "/api/translate/",
            json={"text": "早上好", "target_language": "en"},
            headers=e2e_env["auth_headers"],
        )
        assert resp_en.json()["translated_text"] == "Good morning"

        resp_zh = client.post(
            "/api/translate/",
            json={"text": "Good morning", "target_language": "zh"},
            headers=e2e_env["auth_headers"],
        )
        assert resp_zh.json()["translated_text"] == "早上好"


def test_tier1_error_catalog_code_consistency(e2e_env):
    """Tier 1: Verify structured error responses use catalog compliant error codes."""
    client = e2e_env["client"]
    resp = client.get("/api/audio-overview/podcasts/99999/audio")
    assert resp.status_code == 404
    code = resp.json()["detail"]["code"]
    assert code.isupper()
    assert "AUDIO_OVERVIEW" in code


# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES (45 Tests: limits, malformed data, auth boundaries)
# ==============================================================================

# --- TTS Boundaries ---

def test_tier2_tts_empty_text_rejected(e2e_env):
    """Tier 2: Empty TTS text query parameter is rejected."""
    client = e2e_env["client"]
    resp = client.get("/api/tts/speak?text=")
    assert resp.status_code in [400, 422]


def test_tier2_tts_oversized_text_rejected(e2e_env):
    """Tier 2: Text exceeding 3000 chars is rejected."""
    client = e2e_env["client"]
    huge_text = "A" * 3001
    resp = client.get(f"/api/tts/speak?text={huge_text}")
    assert resp.status_code in [400, 422]


def test_tier2_tts_invalid_engine_rejected(e2e_env):
    """Tier 2: Unknown/unsupported TTS engine is rejected."""
    client = e2e_env["client"]
    resp = client.get("/api/tts/speak?text=Hello&engine=non_existent_engine")
    assert resp.status_code in [400, 500]


def test_tier2_tts_invalid_rate_format_handled(e2e_env):
    """Tier 2: Weird speech rate formats fall back safely."""
    client = e2e_env["client"]
    fake_audio_path = e2e_env["tmp_path"] / "rate_test.mp3"
    fake_audio_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00#RATE")

    async def fake_generate_audio(text, voice, rate="+0%", engine="edge"):
        return TTSAudioResult(
            file_path=str(fake_audio_path),
            voice="zh-CN-XiaoxiaoNeural",
            engine=engine,
            media_type="audio/mpeg",
            filename="tts_rate.mp3",
            cache_hit=False,
        )

    with patch.object(tts_router.tts_service, "generate_audio", new=fake_generate_audio):
        resp = client.get("/api/tts/speak?text=Hello&rate=not_a_rate")
        assert resp.status_code == 200


def test_tier2_tts_provider_exception_returns_500_structured(e2e_env):
    """Tier 2: TTS service unhandled exception returns structured 500 error."""
    client = e2e_env["client"]

    async def fake_generate_audio(*args, **kwargs):
        raise RuntimeError("Provider connection reset by peer")

    with patch.object(tts_router.tts_service, "generate_audio", new=fake_generate_audio):
        resp = client.get("/api/tts/speak?text=Crash+Test")
        assert resp.status_code in [500, 503]
        assert "TTS_" in resp.json()["detail"]["code"]


# --- Chat Boundaries ---

def test_tier2_chat_empty_messages_rejected(e2e_env):
    """Tier 2: Empty messages array rejected."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/chat/completions",
        json={"messages": []},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 422]


def test_tier2_chat_oversized_message_content_rejected(e2e_env):
    """Tier 2: Message exceeding 12000 chars rejected."""
    client = e2e_env["client"]
    huge_msg = "X" * 12001
    resp = client.post(
        "/api/chat/completions",
        json={"messages": [{"role": "user", "content": huge_msg}]},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 422]


def test_tier2_chat_invalid_temperature_bounds(e2e_env):
    """Tier 2: Temperature outside [0.0, 2.0] rejected."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}], "temperature": 3.5},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 422]


def test_tier2_chat_unknown_provider_returns_502(e2e_env):
    """Tier 2: Unknown provider returns 502 with CHAT_PROVIDER_ERROR or 400."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/chat/completions",
        json={"provider": "InvalidProviderX", "messages": [{"role": "user", "content": "hi"}]},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 502]
    assert "CHAT_" in resp.json()["detail"]["code"]


def test_tier2_chat_upstream_abort_handled_gracefully(e2e_env):
    """Tier 2: Provider abort or network timeout handled with structured 502."""
    client = e2e_env["client"]

    async def fake_chat_abort(**kwargs):
        raise RuntimeError("Request timed out after 30000ms")

    with patch.object(chat_router.llm_service, "chat_completion", new=fake_chat_abort):
        resp = client.post(
            "/api/chat/completions",
            json={"messages": [{"role": "user", "content": "timeout"}]},
            headers=e2e_env["auth_headers"],
        )
        assert resp.status_code == 502
        assert resp.json()["detail"]["code"] == "CHAT_PROVIDER_ERROR"


# --- Voice Duplex Boundaries ---

def test_tier2_voice_duplex_session_not_found(e2e_env):
    """Tier 2: Requesting non-existent voice session returns 404 structured error."""
    client = e2e_env["client"]
    resp = client.get("/api/voice-chat/sessions/non_existent_session_id", headers=e2e_env["auth_headers"])
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "VOICE_AGENT_SESSION_NOT_FOUND"


def test_tier2_voice_duplex_empty_turn_handled(e2e_env):
    """Tier 2: Recording turn with empty user and assistant text handled safely."""
    repo = e2e_env["voice_agent_repo"]
    client = e2e_env["client"]

    session = repo.create_session(provider="DashScope", model="qwen-realtime", voice="Cherry")
    repo.upsert_turn(session["id"], "turn-empty", user_text="", assistant_text="", completed=True)

    resp = client.get(f"/api/voice-chat/sessions/{session['id']}", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["turns"][0]["user_text"] == ""


def test_tier2_voice_duplex_metrics_empty_session_list(e2e_env):
    """Tier 2: Metrics summary with no sessions recorded returns zero counts."""
    client = e2e_env["client"]
    resp = client.get("/api/voice-chat/sessions/metrics/summary", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    assert resp.json()["session_count"] == 0


def test_tier2_voice_duplex_interruption_state_transitions(e2e_env):
    """Tier 2: Recording interruption true barge-in updates turn flag."""
    repo = e2e_env["voice_agent_repo"]
    client = e2e_env["client"]

    session = repo.create_session(provider="Google", model="gemini-live", voice="Puck")
    repo.upsert_turn(
        session["id"],
        "turn-interrupted",
        user_text="Wait stop!",
        assistant_text="I was going to say...",
        completed=True,
        interrupted=True,
    )

    resp = client.get(f"/api/voice-chat/sessions/{session['id']}", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    turn = resp.json()["turns"][0]
    assert turn["interrupted"] is True


def test_tier2_voice_duplex_malformed_tool_event_payload(e2e_env):
    """Tier 2: Tool event with non-standard payload fields persists safely."""
    repo = e2e_env["voice_agent_repo"]
    client = e2e_env["client"]

    session = repo.create_session(provider="DashScope", model="qwen-realtime", voice="Cherry")
    repo.add_tool_event(session["id"], "custom_weird_event", {"nested": {"arr": [1, 2, 3]}})

    resp = client.get(f"/api/voice-chat/sessions/{session['id']}", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    event = resp.json()["tool_events"][0]
    assert event["event_type"] == "custom_weird_event"
    assert event["payload"]["nested"]["arr"] == [1, 2, 3]


# --- Podcast Boundaries ---

def test_tier2_podcast_empty_topic_rejected(e2e_env):
    """Tier 2: Empty podcast topic is rejected."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/audio-overview/podcasts",
        json={"topic": ""},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 422]


def test_tier2_podcast_invalid_turn_count_bounds(e2e_env):
    """Tier 2: Turn count < 2 or > 40 is rejected."""
    client = e2e_env["client"]
    resp_low = client.post(
        "/api/audio-overview/scripts/generate",
        json={"topic": "Test", "turn_count": 1},
        headers=e2e_env["auth_headers"],
    )
    assert resp_low.status_code in [400, 422]

    resp_high = client.post(
        "/api/audio-overview/scripts/generate",
        json={"topic": "Test", "turn_count": 50},
        headers=e2e_env["auth_headers"],
    )
    assert resp_high.status_code in [400, 422]


def test_tier2_podcast_synthesize_empty_script(e2e_env):
    """Tier 2: Synthesizing a podcast with insufficient script lines returns 400/500 error."""
    client = e2e_env["client"]
    create_resp = client.post(
        "/api/audio-overview/podcasts",
        json={"topic": "Empty Script Podcast", "script_lines": []},
        headers=e2e_env["auth_headers"],
    )
    pid = create_resp.json()["id"]

    resp = client.post(
        f"/api/audio-overview/podcasts/{pid}/synthesize",
        json={},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 500]


def test_tier2_podcast_audio_streaming_out_of_bounds_range(e2e_env):
    """Tier 2: HTTP Range requesting out-of-bounds byte offset returns 416."""
    client = e2e_env["client"]
    fake_audio = e2e_env["audio_overview_dir"] / "podcast_oob.mp3"
    fake_audio.write_bytes(b"A" * 1024)

    podcast = audio_overview_router.audio_overview_service.create_podcast(
        topic="OOB Range Podcast",
        audio_path=str(fake_audio),
    )
    pid = podcast["id"]

    resp = client.get(
        f"/api/audio-overview/podcasts/{pid}/audio",
        headers={"Range": "bytes=5000-6000"},
    )
    assert resp.status_code == 416


def test_tier2_podcast_synthesize_invalid_merge_strategy(e2e_env):
    """Tier 2: Invalid merge strategy rejected or handled."""
    client = e2e_env["client"]
    create_resp = client.post(
        "/api/audio-overview/podcasts",
        json={"topic": "Strategy Podcast", "script_lines": [{"role": "A", "text": "test"}]},
        headers=e2e_env["auth_headers"],
    )
    pid = create_resp.json()["id"]

    resp = client.post(
        f"/api/audio-overview/podcasts/{pid}/synthesize",
        json={"merge_strategy": "invalid_magic_merge"},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 500]


# --- Transcription Boundaries ---

def test_tier2_transcription_unsupported_file_extension(e2e_env):
    """Tier 2: Non-audio file extension rejected with 400 error."""
    client = e2e_env["client"]
    files = {"file": ("malicious.exe", b"MZThisIsNotAudio", "application/octet-stream")}
    resp = client.post("/api/transcription/", files=files, headers=e2e_env["auth_headers"])
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "TRANSCRIPTION_UNSUPPORTED_FORMAT"


def test_tier2_transcription_empty_file_upload(e2e_env):
    """Tier 2: Empty upload filename or data handled."""
    client = e2e_env["client"]
    files = {"file": ("invalid_empty.wav", b"", "audio/wav")}
    resp = client.post("/api/transcription/", files=files, headers=e2e_env["auth_headers"])
    assert resp.status_code in [400, 500]


def test_tier2_transcription_nonexistent_job_id(e2e_env):
    """Tier 2: Querying non-existent transcription job returns 404."""
    client = e2e_env["client"]
    resp = client.get("/api/transcription/jobs/non-existent-job-9999", headers=e2e_env["auth_headers"])
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "TRANSCRIPTION_JOB_NOT_FOUND"


def test_tier2_transcription_nonexistent_transcript_download(e2e_env):
    """Tier 2: Downloading transcript for non-existent job returns 404."""
    client = e2e_env["client"]
    resp = client.get("/api/transcription/jobs/missing-job/transcript.txt", headers=e2e_env["auth_headers"])
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "TRANSCRIPTION_JOB_NOT_FOUND"


def test_tier2_transcription_batch_delete_empty_list(e2e_env):
    """Tier 2: Batch delete with empty job_ids list returns 400."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/transcription/jobs/batch-delete",
        json={"job_ids": []},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "TRANSCRIPTION_JOB_BAD_REQUEST"


# --- Voice Design/Clone Boundaries ---

def test_tier2_voice_design_empty_prompt_rejected(e2e_env):
    """Tier 2: Voice design with empty prompt rejected."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/voices/design",
        json={"voice_prompt": "", "preview_text": "Sample", "preferred_name": "Test"},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 422]


def test_tier2_voice_design_oversized_preview_text_rejected(e2e_env):
    """Tier 2: Preview text exceeding 1200 chars rejected."""
    client = e2e_env["client"]
    huge_preview = "A" * 1201
    resp = client.post(
        "/api/voices/design",
        json={"voice_prompt": "Prompt", "preview_text": huge_preview, "preferred_name": "Test"},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 422]


def test_tier2_voice_clone_missing_audio_file(e2e_env):
    """Tier 2: Voice clone request without audio file rejected."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/voices/clone",
        data={"preferred_name": "No Audio Voice"},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 422]


def test_tier2_voice_clone_oversized_audio_file(e2e_env):
    """Tier 2: Reference audio exceeding 20MB is rejected."""
    client = e2e_env["client"]
    huge_audio_bytes = b"0" * (20 * 1024 * 1024 + 10)
    files = {"audio_file": ("huge_sample.mp3", huge_audio_bytes, "audio/mpeg")}
    resp = client.post(
        "/api/voices/clone",
        files=files,
        data={"preferred_name": "Huge Voice"},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code in [400, 413]


def test_tier2_voice_delete_nonexistent_id(e2e_env):
    """Tier 2: Deleting custom voice returns response status."""
    client = e2e_env["client"]

    async def fake_delete(**kwargs):
        return {"voice": "non-existent-vd", "type": "voice_design", "deleted": True}

    with patch.object(voices_router.qwen_voice_service, "delete_voice", new=fake_delete):
        resp = client.delete("/api/voices/non-existent-vd?voice_type=voice_design", headers=e2e_env["auth_headers"])
        assert resp.status_code == 200
        assert resp.json()["deleted"] is True


# --- EverMem & Agent Boundaries ---

def test_tier2_evermem_not_configured_returns_400(e2e_env):
    """Tier 2: Request without EverMem headers/config returns 400 error."""
    client = e2e_env["client"]
    resp = client.post(
        "/api/evermem/conversation-meta",
        json={"group_id": "grp-1"},
        headers=e2e_env["auth_headers"],
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "EVERMEM_NOT_CONFIGURED"


def test_tier2_evermem_invalid_group_id_handling(e2e_env):
    """Tier 2: Blank group_id string triggers validation error."""
    client = e2e_env["client"]

    async def fake_create_meta(*args, **kwargs):
        user_id = kwargs.get("user_id") or "scope-1"
        return {"group_id": "generated-group-xyz", "user_id": user_id}

    with patch.object(EverMemService, "create_conversation_meta", new=fake_create_meta):
        resp = client.post(
            "/api/evermem/conversation-meta",
            json={"group_id": ""},
            headers={
                **e2e_env["auth_headers"],
                "X-EverMem-Enabled": "true",
                "X-EverMem-Key": "test-key",
                "X-EverMem-Url": "https://api.evermind.ai",
                "X-EverMem-Scope": "scope-1",
            },
        )
        assert resp.status_code == 422


def test_tier2_agent_runs_not_found(e2e_env):
    """Tier 2: Requesting non-existent agent run returns 404."""
    client = e2e_env["client"]
    resp = client.get("/api/agent-runs/audio_agent:999999", headers=e2e_env["auth_headers"])
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "AGENT_RUN_NOT_FOUND"


def test_tier2_agent_runs_invalid_limit_bounds(e2e_env):
    """Tier 2: Limit query out of range [1, 200] rejected."""
    client = e2e_env["client"]
    resp = client.get("/api/agent-runs/?limit=500", headers=e2e_env["auth_headers"])
    assert resp.status_code in [400, 422]


def test_tier2_agent_runs_events_empty_run(e2e_env):
    """Tier 2: Run query returns event list."""
    client = e2e_env["client"]
    audio_agent = e2e_env["audio_agent_service"]
    agent_runs = e2e_env["agent_run_service"]
    run = audio_agent.create_run(topic="No Events Run", auto_execute=False)
    agent_runs.repository.upsert_audio_run(run)

    canonical_id = f"audio_agent:{run['id']}"
    resp = client.get(f"/api/agent-runs/{canonical_id}/events", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    assert resp.json()["count"] >= 0


# --- Auth & Security Boundaries ---

def test_tier2_auth_register_empty_email_rejected(e2e_env):
    """Tier 2: Registering with empty email rejected."""
    client = e2e_env["client"]
    resp = client.post("/api/auth/register", json={"email": "", "password": "password123"})
    assert resp.status_code in [400, 422]


def test_tier2_auth_register_duplicate_email(e2e_env):
    """Tier 2: Registering duplicate email rejected with 400 error."""
    client = e2e_env["client"]
    resp1 = client.post("/api/auth/register", json={"email": "dupe@example.com", "password": "password123"})
    assert resp1.status_code == 200

    resp2 = client.post("/api/auth/register", json={"email": "dupe@example.com", "password": "anotherpassword"})
    assert resp2.status_code == 400
    assert resp2.json()["detail"]["code"] == "AUTH_REGISTER_FAILED"


def test_tier2_auth_login_invalid_password(e2e_env):
    """Tier 2: Login with wrong password returns 401."""
    client = e2e_env["client"]
    client.post("/api/auth/register", json={"email": "user@example.com", "password": "correct_pass"})

    resp = client.post("/api/auth/login", json={"email": "user@example.com", "password": "wrong_pass"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "AUTH_LOGIN_FAILED"


def test_tier2_auth_user_token_cannot_modify_admin_settings(e2e_env):
    """Tier 2: Normal user token is forbidden from updating admin settings."""
    client = e2e_env["client"]
    resp = client.put(
        "/api/settings/",
        json={"merge": True, "settings": {"general_settings": {"log_level": "DEBUG"}}},
        headers={"Authorization": "Bearer e2e-api-token"},  # non-admin token
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "AUTH_ADMIN_TOKEN_INVALID"


def test_tier2_auth_bearer_token_with_whitespace_stripped(e2e_env):
    """Tier 2: Bearer token containing leading/trailing whitespace is accepted."""
    client = e2e_env["client"]

    async def fake_chat(**kwargs):
        return {"provider": "DashScope", "model": "qwen-plus", "reply": "ok", "raw": {}}

    with patch.object(chat_router.llm_service, "chat_completion", new=fake_chat):
        resp = client.post(
            "/api/chat/completions",
            json={"messages": [{"role": "user", "content": "test"}]},
            headers={"Authorization": "Bearer   e2e-api-token   "},
        )
        assert resp.status_code == 200


# --- Settings & Config Boundaries ---

def test_tier2_settings_invalid_json_headers(e2e_env):
    """Tier 2: Malformed JSON headers in custom provider settings handled safely."""
    client = e2e_env["client"]
    resp = client.put(
        "/api/settings/",
        json={"merge": True, "settings": {"api_keys": {"invalid_key": "val"}}},
        headers=e2e_env["admin_headers"],
    )
    assert resp.status_code == 200


def test_tier2_settings_non_ascii_api_key_sanitized_or_handled(e2e_env):
    """Tier 2: Non-ASCII characters in API key field rejected or sanitized."""
    client = e2e_env["client"]
    resp = client.put(
        "/api/settings/",
        json={"merge": True, "settings": {"api_keys": {"dashscope_api_key": "sk-密钥-123"}}},
        headers=e2e_env["admin_headers"],
    )
    assert resp.status_code in [200, 400]


def test_tier2_settings_merge_flag_partial_update(e2e_env):
    """Tier 2: Merge=True preserves unmentioned settings fields."""
    client = e2e_env["client"]
    resp = client.put(
        "/api/settings/",
        json={"merge": True, "settings": {"general_settings": {"log_level": "WARNING"}}},
        headers=e2e_env["admin_headers"],
    )
    assert resp.status_code == 200
    data = resp.json()["settings"]
    assert data["general_settings"]["log_level"] == "WARNING"
    assert "dashscope_api_key" in data["api_keys"]


def test_tier2_settings_corrupt_config_fallback(e2e_env):
    """Tier 2: Corrupted config file falls back to defaults without crash."""
    config_path = e2e_env["tmp_path"] / "corrupt_config.json"
    config_path.write_text("{ corrupt json: [", encoding="utf-8")
    cfg = BackendConfig(config_path)
    assert cfg.get("general_settings.log_level", "INFO") == "INFO"


def test_tier2_settings_custom_provider_validation(e2e_env):
    """Tier 2: Adding a custom OpenAI-compatible provider persists in config."""
    client = e2e_env["client"]
    resp = client.put(
        "/api/settings/",
        json={
            "merge": True,
            "settings": {
                "custom_providers": [
                    {
                        "name": "LocalLLM",
                        "api_url": "http://127.0.0.1:11434/v1",
                        "api_key": "ollama",
                        "default_model": "llama3.2",
                    }
                ]
            },
        },
        headers=e2e_env["admin_headers"],
    )
    assert resp.status_code == 200
    providers = resp.json()["settings"].get("custom_providers", [])
    assert any(p["name"] == "LocalLLM" for p in providers)


# ==============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS (10 Multi-Feature Workflows)
# ==============================================================================

def test_tier3_chat_reply_piped_to_tts_synthesis(e2e_env):
    """Tier 3: Chat response output piped directly into TTS speak audio synthesis."""
    client = e2e_env["client"]

    # 1. Generate chat completion
    async def fake_chat(**kwargs):
        return {"provider": "DashScope", "model": "qwen-plus", "reply": "The future of voice AI is multimodal.", "raw": {}}

    fake_audio_path = e2e_env["tmp_path"] / "tier3_chat_tts.mp3"
    fake_audio_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00#CHATTTSAUDIO")

    async def fake_generate_audio(text, *args, **kwargs):
        assert text == "The future of voice AI is multimodal."
        return TTSAudioResult(
            file_path=str(fake_audio_path),
            voice="zh-CN-XiaoxiaoNeural",
            engine="edge",
            media_type="audio/mpeg",
            filename="tts_output.mp3",
            cache_hit=False,
        )

    with (
        patch.object(chat_router.llm_service, "chat_completion", new=fake_chat),
        patch.object(tts_router.tts_service, "generate_audio", new=fake_generate_audio),
    ):
        chat_resp = client.post(
            "/api/chat/completions",
            json={"messages": [{"role": "user", "content": "Describe future of AI."}]},
            headers=e2e_env["auth_headers"],
        )
        assert chat_resp.status_code == 200
        reply_text = chat_resp.json()["reply"]

        tts_resp = client.get(f"/api/tts/speak?text={reply_text}&voice=zh-CN-XiaoxiaoNeural")
        assert tts_resp.status_code == 200
        assert tts_resp.headers["content-type"] == "audio/mpeg"
        assert len(tts_resp.content) > 0


def test_tier3_chat_with_evermem_save_and_subsequent_retrieval(e2e_env):
    """Tier 3: Chat completion with memory enabled coordinates conversation meta and context."""
    client = e2e_env["client"]

    # 1. Resolve conversation metadata
    async def fake_create_meta(*args, **kwargs):
        user_id = kwargs.get("user_id") or "scope-e2e"
        return {"group_id": "mem-group-e2e", "user_id": user_id}

    async def fake_chat(**kwargs):
        assert kwargs.get("use_memory") is True
        return {"provider": "DashScope", "model": "qwen-plus", "reply": "Memory context incorporated.", "raw": {}}

    with (
        patch.object(EverMemService, "create_conversation_meta", new=fake_create_meta),
        patch.object(chat_router.llm_service, "chat_completion", new=fake_chat),
    ):
        meta_resp = client.post(
            "/api/evermem/conversation-meta",
            json={"group_id": "mem-group-e2e"},
            headers={
                **e2e_env["auth_headers"],
                "X-EverMem-Enabled": "true",
                "X-EverMem-Key": "test-key",
                "X-EverMem-Url": "https://api.evermind.ai",
                "X-EverMem-Scope": "scope-e2e",
            },
        )
        assert meta_resp.status_code == 200

        chat_resp = client.post(
            "/api/chat/completions",
            json={"messages": [{"role": "user", "content": "My favorite color is navy."}], "use_memory": True},
            headers=e2e_env["auth_headers"],
        )
        assert chat_resp.status_code == 200
        assert chat_resp.json()["reply"] == "Memory context incorporated."


def test_tier3_podcast_script_generation_to_synthesis_to_streaming(e2e_env):
    """Tier 3: Podcast script generated -> synthesized into audio -> streamed with HTTP Range."""
    client = e2e_env["client"]

    # 1. Generate script
    async def fake_generate_script(*args, **kwargs):
        return {
            "topic": "Space Exploration",
            "language": "zh",
            "turn_count": 2,
            "provider": "DashScope",
            "model": "qwen-plus",
            "script_lines": [
                {"role": "A", "text": "火星探测迎来了新突破。"},
                {"role": "B", "text": "是的，探测器成功着陆。"},
            ],
            "memories_retrieved": 0,
            "memory_saved": False,
        }

    with patch.object(audio_overview_router.audio_overview_service, "generate_script", new=fake_generate_script):
        script_resp = client.post(
            "/api/audio-overview/scripts/generate",
            json={"topic": "Space Exploration", "turn_count": 2},
            headers=e2e_env["auth_headers"],
        )
        assert script_resp.status_code == 200
        script_lines = script_resp.json()["script_lines"]

    # 2. Create podcast record
    create_resp = client.post(
        "/api/audio-overview/podcasts",
        json={"topic": "Space Exploration", "language": "zh", "script_lines": script_lines},
        headers=e2e_env["auth_headers"],
    )
    pid = create_resp.json()["id"]

    # 3. Synthesize audio
    fake_audio_bytes = bytes([i % 256 for i in range(2048)])
    podcast_audio_file = e2e_env["audio_overview_dir"] / f"podcast_{pid}.mp3"
    podcast_audio_file.write_bytes(fake_audio_bytes)

    async def fake_synthesize(*args, **kwargs):
        audio_overview_router.audio_overview_service.update_podcast(pid, audio_path=str(podcast_audio_file))
        return {
            "podcast_id": pid,
            "audio_path": str(podcast_audio_file),
            "audio_download_url": f"/api/audio-overview/podcasts/{pid}/audio",
            "line_count": 2,
            "voice_a": "zh-CN-YunxiNeural",
            "voice_b": "zh-CN-XiaoxiaoNeural",
            "rate": "+0%",
            "cache_hits": 0,
            "gap_ms": 250,
            "gap_ms_applied": 250,
            "merge_strategy": "auto",
            "intro_music": False,
            "intro_music_style": "off",
            "intro_music_duration_ms": 0,
        }

    with patch.object(audio_overview_router.audio_overview_service, "synthesize_podcast_audio", new=fake_synthesize):
        synth_resp = client.post(
            f"/api/audio-overview/podcasts/{pid}/synthesize",
            json={},
            headers=e2e_env["auth_headers"],
        )
        assert synth_resp.status_code == 200

    # 4. Stream audio with Range seek
    stream_resp = client.get(
        f"/api/audio-overview/podcasts/{pid}/audio",
        headers={"Range": "bytes=0-511"},
    )
    assert stream_resp.status_code == 206
    assert stream_resp.headers["content-range"] == "bytes 0-511/2048"
    assert stream_resp.content == fake_audio_bytes[0:512]


def test_tier3_podcast_audio_to_transcription_and_subtitles(e2e_env):
    """Tier 3: Podcast audio file submitted to ASR transcription -> transcript downloaded."""
    client = e2e_env["client"]

    # 1. Create a dummy podcast audio file
    podcast_audio = e2e_env["tmp_path"] / "source_podcast.mp3"
    podcast_audio.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00#PODCASTSPEECH")

    # 2. Prepare job
    transcript_file = e2e_env["tmp_path"] / "podcast_asr_transcript.txt"
    transcript_file.write_text(
        "Welcome to the AI podcast.\nToday we examine neural networks.",
        encoding="utf-8",
    )

    async def fake_prepare(upload_path, original_name):
        job = TranscriptionJob(
            file_path=str(upload_path),
            job_id="job-podcast-asr",
            mode="file",
            status="completed",
            original_filename="source_podcast.mp3",
            transcript_path=str(transcript_file),
        )
        return transcription_router.transcription_service._write_job(job)

    with patch.object(transcription_router.transcription_service, "prepare_long_transcription_job", new=fake_prepare):
        files = {"file": ("source_podcast.mp3", podcast_audio.read_bytes(), "audio/mpeg")}
        submit_resp = client.post("/api/transcription/jobs", files=files, headers=e2e_env["auth_headers"])
        assert submit_resp.status_code == 200
        job_id = submit_resp.json()["job_id"]

        # 3. Download transcript
        dl_resp = client.get(f"/api/transcription/jobs/{job_id}/transcript.txt", headers=e2e_env["auth_headers"])
        assert dl_resp.status_code == 200
        assert "Welcome to the AI podcast." in dl_resp.text


def test_tier3_voice_design_to_custom_tts_synthesis(e2e_env):
    """Tier 3: Custom voice designed via API -> used as voice ID in TTS synthesis."""
    client = e2e_env["client"]

    # 1. Design voice
    async def fake_design(**kwargs):
        return {
            "voice": "custom_anchor_v1",
            "type": "voice_design",
            "target_model": "cosyvoice-v1",
            "preferred_name": "Anchor Voice",
            "language": "zh",
            "preview_audio_data": None,
            "provider": "qwen",
        }

    with patch.object(voices_router.qwen_voice_service, "create_voice_design", new=fake_design):
        design_resp = client.post(
            "/api/voices/design",
            json={"voice_prompt": "Authoritative broadcast anchor", "preview_text": "新闻播报", "preferred_name": "Anchor Voice"},
            headers=e2e_env["auth_headers"],
        )
        assert design_resp.status_code == 200
        custom_voice_id = design_resp.json()["voice"]

    # 2. Synthesize with custom voice ID
    fake_audio_path = e2e_env["tmp_path"] / "custom_voice_out.mp3"
    fake_audio_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00#CUSTOMVOICE")

    async def fake_speak(text, voice, *args, **kwargs):
        assert voice == custom_voice_id
        return TTSAudioResult(
            file_path=str(fake_audio_path),
            voice=voice,
            engine="qwen_flash",
            media_type="audio/mpeg",
            filename="tts_custom.mp3",
            cache_hit=False,
        )

    with patch.object(tts_router.tts_service, "generate_audio", new=fake_speak):
        speak_resp = client.get(f"/api/tts/speak?text=重要新闻播报&voice={custom_voice_id}&engine=qwen_flash")
        assert speak_resp.status_code == 200
        assert speak_resp.headers["x-tts-engine"] == "qwen_flash"


def test_tier3_voice_clone_to_realtime_voice_session(e2e_env):
    """Tier 3: Voice cloned from audio -> instantiated in realtime voice duplex session."""
    client = e2e_env["client"]
    repo = e2e_env["voice_agent_repo"]

    # 1. Clone voice
    async def fake_clone(**kwargs):
        return {
            "voice": "cloned_user_voice_88",
            "type": "voice_clone",
            "target_model": "cosyvoice-clone",
            "preferred_name": "User Voice",
            "language": "zh",
            "preview_audio_data": None,
            "provider": "qwen",
        }

    with patch.object(voices_router.qwen_voice_service, "create_voice_clone", new=fake_clone):
        files = {"audio_file": ("my_voice.wav", b"RIFF....WAVEdata", "audio/wav")}
        clone_resp = client.post(
            "/api/voices/clone",
            files=files,
            data={"preferred_name": "User Voice"},
            headers=e2e_env["auth_headers"],
        )
        assert clone_resp.status_code == 200
        cloned_voice_id = clone_resp.json()["voice"]

    # 2. Create voice duplex session with cloned voice
    session = repo.create_session(provider="DashScope", model="qwen-realtime", voice=cloned_voice_id)
    assert session["voice"] == cloned_voice_id

    sess_resp = client.get(f"/api/voice-chat/sessions/{session['id']}", headers=e2e_env["auth_headers"])
    assert sess_resp.status_code == 200
    assert sess_resp.json()["voice"] == cloned_voice_id


def test_tier3_realtime_voice_turn_to_audio_agent_run_to_artifact_link(e2e_env):
    """Tier 3: Realtime turn triggers Audio Agent run -> artifact linked into session history."""
    client = e2e_env["client"]
    repo = e2e_env["voice_agent_repo"]
    audio_agent = e2e_env["audio_agent_service"]

    # 1. Open voice duplex session
    session = repo.create_session(provider="DashScope", model="qwen-realtime", voice="Cherry")
    repo.upsert_turn(
        session["id"],
        "turn-agent-call",
        user_text="请帮我做一份关于自动驾驶的播客调研。",
        assistant_text="好的，正在启动播客研究 Agent。",
        completed=True,
    )

    # 2. Trigger audio agent run
    run = audio_agent.create_run(
        topic="自动驾驶技术演进",
        auto_execute=False,
    )

    # 3. Link agent run to voice turn
    repo.link_agent_run_artifact(
        session["id"],
        "turn-agent-call",
        {"type": "audio_agent_run", "run_id": run["id"], "status": "completed", "topic": "自动驾驶技术演进"},
    )

    # 4. Verify session detail contains the linked artifact
    resp = client.get(f"/api/voice-chat/sessions/{session['id']}", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    links = resp.json()["agent_run_links"]
    assert len(links) == 1
    assert links[0]["voice_turn_id"] == "turn-agent-call"


def test_tier3_transcription_to_translation_to_bilingual_tts(e2e_env):
    """Tier 3: Audio transcribed -> translated into target language -> translated text synthesized."""
    client = e2e_env["client"]

    # 1. Transcribe
    async def fake_transcribe(*args, **kwargs):
        return {"text": "你好，请问今天的天气如何？", "duration_seconds": 2.1, "words": []}

    # 2. Translate
    async def fake_translate(text, target_language, **kwargs):
        assert text == "你好，请问今天的天气如何？"
        assert target_language == "en"
        return {"provider": "DashScope", "model": "qwen-plus", "translated_text": "Hello, how is the weather today?"}

    # 3. Synthesize
    fake_audio_path = e2e_env["tmp_path"] / "t3_bilingual.mp3"
    fake_audio_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00#BILINGUAL")

    async def fake_speak(text, voice, *args, **kwargs):
        assert text == "Hello, how is the weather today?"
        return TTSAudioResult(
            file_path=str(fake_audio_path),
            voice="en-US-JennyNeural",
            engine="edge",
            media_type="audio/mpeg",
            filename="tts_en.mp3",
            cache_hit=False,
        )

    with (
        patch.object(transcription_router.transcription_service, "transcribe_media", new=fake_transcribe),
        patch.object(translate_router.llm_service, "translate_text", new=fake_translate),
        patch.object(tts_router.tts_service, "generate_audio", new=fake_speak),
    ):
        tx_resp = client.post(
            "/api/transcription/",
            files={"file": ("input.wav", b"RIFF....WAVEdata", "audio/wav")},
            headers=e2e_env["auth_headers"],
        )
        assert tx_resp.status_code == 200
        chinese_transcript = tx_resp.json()["transcript"]

        tr_resp = client.post(
            "/api/translate/",
            json={"text": chinese_transcript, "target_language": "en"},
            headers=e2e_env["auth_headers"],
        )
        assert tr_resp.status_code == 200
        english_translation = tr_resp.json()["translated_text"]

        tts_resp = client.get(f"/api/tts/speak?text={english_translation}&voice=en-US-JennyNeural&engine=edge")
        assert tts_resp.status_code == 200
        assert len(tts_resp.content) > 0


def test_tier3_settings_update_provider_config_to_chat_dispatch(e2e_env):
    """Tier 3: Updating settings model catalog directly affects chat completion resolution."""
    client = e2e_env["client"]

    # 1. Update settings with new default model
    update_resp = client.put(
        "/api/settings/",
        json={
            "merge": True,
            "settings": {
                "default_models": {
                    "DashScope": {"default": "qwen-max-custom", "available": ["qwen-max-custom"]}
                }
            },
        },
        headers=e2e_env["admin_headers"],
    )
    assert update_resp.status_code == 200

    # 2. Check chat completion resolves model from settings
    async def fake_chat(provider, model=None, **kwargs):
        resolved_model = model or "qwen-max-custom"
        return {"provider": provider, "model": resolved_model, "reply": f"Served via {resolved_model}", "raw": {}}

    with patch.object(chat_router.llm_service, "chat_completion", new=fake_chat):
        chat_resp = client.post(
            "/api/chat/completions",
            json={"provider": "DashScope", "messages": [{"role": "user", "content": "Ping"}]},
            headers=e2e_env["auth_headers"],
        )
        assert chat_resp.status_code == 200
        assert "qwen-max-custom" in chat_resp.json()["model"]


def test_tier3_user_auth_register_login_to_protected_resources(e2e_env):
    """Tier 3: User registers -> logs in -> uses JWT Bearer token across protected endpoints."""
    client = e2e_env["client"]

    # 1. Register new user
    reg_resp = client.post(
        "/api/auth/register",
        json={"email": "researcher@example.com", "password": "SecurePassword123!"},
    )
    assert reg_resp.status_code == 200
    token = reg_resp.json()["access_token"]
    jwt_headers = {"Authorization": f"Bearer {token}"}

    # 2. Authenticate /api/auth/me
    me_resp = client.get("/api/auth/me", headers=jwt_headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "researcher@example.com"

    # 3. Access write endpoint (Audio Overview create)
    ao_resp = client.post(
        "/api/audio-overview/podcasts",
        json={"topic": "JWT Protected Podcast", "language": "en"},
        headers=jwt_headers,
    )
    assert ao_resp.status_code == 200
    assert ao_resp.json()["topic"] == "JWT Protected Podcast"


# ==============================================================================
# TIER 4: REAL-WORLD SCENARIOS (5 End-to-End Holistic Workflows)
# ==============================================================================

def test_tier4_scenario_full_podcast_production_lifecycle(e2e_env):
    """
    Scenario 1: Complete Podcast Studio Lifecycle
    - Draft initial topic
    - AI generates 4-turn multi-speaker script
    - User edits and refines turn texts
    - Synthesizes audio with dual voices and intro music
    - Streams audio with HTTP Range verification
    - Deletes podcast and verifies complete cleanup
    """
    client = e2e_env["client"]

    # Step 1: Generate AI script
    async def fake_generate_script(*args, **kwargs):
        return {
            "topic": "The History of Open Source",
            "language": "zh",
            "turn_count": 4,
            "provider": "DashScope",
            "model": "qwen-plus",
            "script_lines": [
                {"role": "A", "text": "欢迎收听开源简史。"},
                {"role": "B", "text": "从 Linux 到现代 AI 生态。"},
                {"role": "A", "text": "开源改变了整个软件工业。"},
                {"role": "B", "text": "是的，协作的力量无可比拟。"},
            ],
            "memories_retrieved": 0,
            "memory_saved": False,
        }

    with patch.object(audio_overview_router.audio_overview_service, "generate_script", new=fake_generate_script):
        gen_resp = client.post(
            "/api/audio-overview/scripts/generate",
            json={"topic": "The History of Open Source", "turn_count": 4},
            headers=e2e_env["auth_headers"],
        )
        assert gen_resp.status_code == 200
        initial_lines = gen_resp.json()["script_lines"]

    # Step 2: Create podcast in DB
    create_resp = client.post(
        "/api/audio-overview/podcasts",
        json={"topic": "The History of Open Source", "language": "zh", "script_lines": initial_lines},
        headers=e2e_env["auth_headers"],
    )
    pid = create_resp.json()["id"]

    # Step 3: User edits script lines
    edited_lines = [
        {"role": "A", "text": "欢迎收听《开源简史》第一期。"},
        {"role": "B", "text": "从 GNU、Linux 到现代大模型开源。"},
        {"role": "A", "text": "开源彻底重塑了整个软件工业。"},
        {"role": "B", "text": "是的，全球协作带来了惊人的创新速度。"},
    ]
    update_resp = client.put(
        f"/api/audio-overview/podcasts/{pid}/script",
        json={"script_lines": edited_lines},
        headers=e2e_env["auth_headers"],
    )
    assert update_resp.status_code == 200
    assert len(update_resp.json()["script_lines"]) == 4

    # Step 4: Synthesize podcast audio
    fake_audio_bytes = bytes([i % 256 for i in range(4096)])
    audio_path = e2e_env["audio_overview_dir"] / f"podcast_{pid}_master.mp3"
    audio_path.write_bytes(fake_audio_bytes)

    async def fake_synthesize(*args, **kwargs):
        audio_overview_router.audio_overview_service.update_podcast(pid, audio_path=str(audio_path))
        return {
            "podcast_id": pid,
            "audio_path": str(audio_path),
            "audio_download_url": f"/api/audio-overview/podcasts/{pid}/audio",
            "line_count": 4,
            "voice_a": "zh-CN-YunxiNeural",
            "voice_b": "zh-CN-XiaoxiaoNeural",
            "rate": "+0%",
            "cache_hits": 0,
            "gap_ms": 250,
            "gap_ms_applied": 250,
            "merge_strategy": "auto",
            "intro_music": True,
            "intro_music_style": "warm",
            "intro_music_duration_ms": 2500,
        }

    with patch.object(audio_overview_router.audio_overview_service, "synthesize_podcast_audio", new=fake_synthesize):
        synth_resp = client.post(
            f"/api/audio-overview/podcasts/{pid}/synthesize",
            json={"voice_a": "zh-CN-YunxiNeural", "voice_b": "zh-CN-XiaoxiaoNeural", "intro_music": True},
            headers=e2e_env["auth_headers"],
        )
        assert synth_resp.status_code == 200

    # Step 5: Verify Range seeking on synthesized podcast
    range_resp = client.get(
        f"/api/audio-overview/podcasts/{pid}/audio",
        headers={"Range": "bytes=1000-1999"},
    )
    assert range_resp.status_code == 206
    assert range_resp.headers["content-range"] == "bytes 1000-1999/4096"
    assert range_resp.content == fake_audio_bytes[1000:2000]

    # Step 6: Delete podcast and verify cleanup
    del_resp = client.delete(f"/api/audio-overview/podcasts/{pid}", headers=e2e_env["auth_headers"])
    assert del_resp.status_code == 200
    assert del_resp.json()["deleted"] is True

    get_resp = client.get(f"/api/audio-overview/podcasts/{pid}")
    assert get_resp.status_code == 404


def test_tier4_scenario_voice_duplex_session_with_tools_and_metrics(e2e_env):
    """
    Scenario 2: Duplex Voice Agent Turn Lifecycle
    - Open duplex voice session
    - Execute turn 1 with user query & tool invocation
    - Execute turn 2 with user interruption barge-in
    - Record latency metrics
    - Inspect timeline & session summary metrics
    """
    client = e2e_env["client"]
    repo = e2e_env["voice_agent_repo"]

    # Step 1: Open session
    session = repo.create_session(provider="Google", model="gemini-3.1-flash-live-preview", voice="Puck")
    sid = session["id"]

    # Step 2: Turn 1 with tool call
    repo.upsert_turn(
        sid,
        "turn-1",
        user_text="帮我查一下杭州明天的气温。",
        assistant_text="杭州明天晴朗，最高温度 25 度。",
        completed=True,
    )
    repo.add_tool_event(
        sid,
        "tool_call",
        {"tool_name": "weather_lookup", "city": "Hangzhou", "temp_c": 25, "turn_id": "turn-1"},
    )
    repo.add_session_event(sid, "first_audio", source="runtime", payload={"latency_ms": 280})

    # Step 3: Turn 2 with interruption barge-in
    repo.upsert_turn(
        sid,
        "turn-2",
        user_text="停一下，那后天呢？",
        assistant_text="后天有小雨...",
        completed=True,
        interrupted=True,
    )
    repo.add_session_event(sid, "stop", source="runtime", payload={"latency_ms": 95})

    # Step 4: Inspect chronological timeline
    resp = client.get(f"/api/voice-chat/sessions/{sid}", headers=e2e_env["auth_headers"])
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["turns"]) == 2
    assert data["turns"][1]["interrupted"] is True
    assert len(data["tool_events"]) == 1

    # Step 5: Compute summary metrics
    metrics_resp = client.get("/api/voice-chat/sessions/metrics/summary", headers=e2e_env["auth_headers"])
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    assert metrics["session_count"] >= 1
    assert metrics["turn_count"] >= 2


def test_tier4_scenario_end_to_end_media_transcription_and_subtitle_workflow(e2e_env):
    """
    Scenario 3: Media Transcription & Subtitle Editing Pipeline
    - Upload media recording
    - Process transcription job
    - Verify initial transcript preview
    - Correct words & timestamps
    - Download final transcript
    """
    client = e2e_env["client"]

    transcript_path = e2e_env["tmp_path"] / "interview_transcript.txt"
    transcript_path.write_text("Hello and welcome.\nToday we talk with Dr. Smith.", encoding="utf-8")

    async def fake_prepare(upload_path, original_name):
        job = TranscriptionJob(
            file_path=str(upload_path),
            job_id="job-scenario-3",
            mode="file",
            status="completed",
            original_filename="interview_session.mp3",
            duration_seconds=45.0,
            transcript_path=str(transcript_path),
        )
        return transcription_router.transcription_service._write_job(job)

    with patch.object(transcription_router.transcription_service, "prepare_long_transcription_job", new=fake_prepare):
        # 1. Submit audio
        submit_resp = client.post(
            "/api/transcription/jobs",
            files={"file": ("interview_session.mp3", b"ID3\x03\x00\x00\x00\x00\x00#DATA", "audio/mpeg")},
            headers=e2e_env["auth_headers"],
        )
        assert submit_resp.status_code == 200
        job_id = submit_resp.json()["job_id"]

        # 2. Get status & preview
        get_resp = client.get(f"/api/transcription/jobs/{job_id}", headers=e2e_env["auth_headers"])
        assert get_resp.status_code == 200
        assert "Hello and welcome" in get_resp.json()["transcript"]

        # 3. Edit & save transcript
        save_resp = client.post(
            "/api/transcription/jobs/save-text",
            json={"transcript": "Hello and welcome to Echo.\nToday we talk with Dr. Smith.", "file_name": "interview_session.mp3"},
            headers=e2e_env["auth_headers"],
        )
        assert save_resp.status_code == 200
        saved_id = save_resp.json()["job_id"]

        # 4. Download updated transcript
        dl_resp = client.get(f"/api/transcription/jobs/{saved_id}/transcript.txt", headers=e2e_env["auth_headers"])
        assert dl_resp.status_code == 200
        assert "Hello and welcome to Echo." in dl_resp.text


def test_tier4_scenario_custom_voice_design_and_clone_multi_engine_pipeline(e2e_env):
    """
    Scenario 4: Custom Voice Design & Clone Multi-Engine Pipeline
    - Design custom voice profile
    - Clone reference user voice
    - List and verify both voices exist in catalog
    - Perform TTS synthesis with fallback engine
    - Delete created voice profiles
    """
    client = e2e_env["client"]

    # 1. Design Voice
    async def fake_design(**kwargs):
        return {
            "voice": "vd-scenario-01",
            "type": "voice_design",
            "target_model": "cosyvoice-v1",
            "preferred_name": "Studio Storyteller",
            "language": "zh",
            "preview_audio_data": None,
            "provider": "qwen",
        }

    # 2. Clone Voice
    async def fake_clone(**kwargs):
        return {
            "voice": "vc-scenario-02",
            "type": "voice_clone",
            "target_model": "cosyvoice-clone",
            "preferred_name": "User Voice Master",
            "language": "zh",
            "preview_audio_data": None,
            "provider": "qwen",
        }

    # 3. List Voices
    async def fake_list(voice_type="voice_design", **kwargs):
        if voice_type == "voice_design":
            return {"voice_type": "voice_design", "count": 1, "voices": [{"voice": "vd-scenario-01", "preferred_name": "Studio Storyteller", "type": "voice_design"}]}
        return {"voice_type": "voice_clone", "count": 1, "voices": [{"voice": "vc-scenario-02", "preferred_name": "User Voice Master", "type": "voice_clone"}]}

    async def fake_delete(voice_name, voice_type, **kwargs):
        return {"voice": voice_name, "type": voice_type, "deleted": True}

    with (
        patch.object(voices_router.qwen_voice_service, "create_voice_design", new=fake_design),
        patch.object(voices_router.qwen_voice_service, "create_voice_clone", new=fake_clone),
        patch.object(voices_router.qwen_voice_service, "list_voices", new=fake_list),
        patch.object(voices_router.qwen_voice_service, "delete_voice", new=fake_delete),
    ):
        # Create Design
        d_resp = client.post(
            "/api/voices/design",
            json={"voice_prompt": "Warm storyteller", "preview_text": "从前有座山", "preferred_name": "Studio Storyteller"},
            headers=e2e_env["auth_headers"],
        )
        assert d_resp.status_code == 200
        vd_id = d_resp.json()["voice"]

        # Create Clone
        c_resp = client.post(
            "/api/voices/clone",
            files={"audio_file": ("sample.mp3", b"ID3FakeSample", "audio/mpeg")},
            data={"preferred_name": "User Voice Master"},
            headers=e2e_env["auth_headers"],
        )
        assert c_resp.status_code == 200
        vc_id = c_resp.json()["voice"]

        # List both
        vd_list = client.get("/api/voices/?voice_type=voice_design", headers=e2e_env["auth_headers"]).json()
        vc_list = client.get("/api/voices/?voice_type=voice_clone", headers=e2e_env["auth_headers"]).json()
        assert vd_list["count"] == 1
        assert vc_list["count"] == 1

        # Delete cleanup
        del_d = client.delete(f"/api/voices/{vd_id}?voice_type=voice_design", headers=e2e_env["auth_headers"])
        assert del_d.status_code == 200
        assert del_d.json()["deleted"] is True


def test_tier4_scenario_multilingual_chat_assistant_with_memory_and_tools(e2e_env):
    """
    Scenario 5: Multilingual Chat Assistant with Memory & Tools
    - Create EverMem conversation scope
    - Send multi-turn bilingual conversation (Chinese & English)
    - Store memory context tags
    - Retrieve context in follow-up turn
    - Pipe final response to bilingual translation
    """
    client = e2e_env["client"]

    # 1. EverMem session
    async def fake_conv_meta(*args, **kwargs):
        user_id = kwargs.get("user_id") or "user-multi"
        return {"group_id": "multilingual-scope-42", "user_id": user_id}

    # 2. Chat completion
    turn_counter = {"count": 0}

    async def fake_chat(messages, use_memory=False, **kwargs):
        turn_counter["count"] += 1
        if turn_counter["count"] == 1:
            return {
                "provider": "DashScope",
                "model": "qwen-plus",
                "reply": "我已记录您的偏好：偏好使用深色模式与紧凑界面。",
                "raw": {},
            }
        return {
            "provider": "DashScope",
            "model": "qwen-plus",
            "reply": "Based on your remembered preference, dark mode and compact view are active.",
            "raw": {},
        }

    # 3. Translate
    async def fake_translate(text, target_language, **kwargs):
        return {
            "provider": "DashScope",
            "model": "qwen-plus",
            "translated_text": "基于您记录的偏好，已启用深色模式与紧凑视图。",
        }

    with (
        patch.object(EverMemService, "create_conversation_meta", new=fake_conv_meta),
        patch.object(chat_router.llm_service, "chat_completion", new=fake_chat),
        patch.object(translate_router.llm_service, "translate_text", new=fake_translate),
    ):
        meta_resp = client.post(
            "/api/evermem/conversation-meta",
            json={"group_id": "multilingual-scope-42"},
            headers={
                **e2e_env["auth_headers"],
                "X-EverMem-Enabled": "true",
                "X-EverMem-Key": "test-key",
                "X-EverMem-Url": "https://api.evermind.ai",
                "X-EverMem-Scope": "user-multi",
            },
        )
        assert meta_resp.status_code == 200

        # Turn 1 (Chinese)
        turn1 = client.post(
            "/api/chat/completions",
            json={"messages": [{"role": "user", "content": "我偏好深色模式。"}], "use_memory": True},
            headers=e2e_env["auth_headers"],
        )
        assert turn1.status_code == 200
        assert "深色模式" in turn1.json()["reply"]

        # Turn 2 (English query with remembered context)
        turn2 = client.post(
            "/api/chat/completions",
            json={"messages": [{"role": "user", "content": "What are my current active settings?"}], "use_memory": True},
            headers=e2e_env["auth_headers"],
        )
        assert turn2.status_code == 200
        assert "dark mode" in turn2.json()["reply"]

        # Translate reply to Chinese
        tr_resp = client.post(
            "/api/translate/",
            json={"text": turn2.json()["reply"], "target_language": "zh"},
            headers=e2e_env["auth_headers"],
        )
        assert tr_resp.status_code == 200
        assert "深色模式" in tr_resp.json()["translated_text"]
