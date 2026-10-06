# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Voice Spirit 2.0 is a web-based desktop application for AI-powered voice synthesis and chat. It uses a FastAPI backend + React (Vite/TypeScript) frontend architecture, with an optional pywebview wrapper for desktop mode. It supports multiple TTS engines (Edge TTS, Google Gemini TTS, Qwen TTS, MiniMax, OpenAI, ElevenLabs, ChatTTS, GPT-SoVITS, Xiaomi) and AI model APIs (DeepSeek, OpenRouter, Groq, SiliconFlow, Google Gemini, DashScope, Ollama).

## Commands

### Backend Python environment
The backend runs in a dedicated venv at `backend/.venv`, built from the installer's lock file (never the global Conda env):
```bash
cd backend
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-packaging.lock -r ..\desktop_requirements.txt
```
`run_web.bat` / `run_web_desktop.bat` pick it up automatically (falling back to `python` on PATH). Rebuild it when `requirements-packaging.lock` changes.

### Run (Development)
```bash
# Start backend + frontend dev servers (two windows)
run_web.bat

# Or manually:
cd backend && .venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
cd frontend && npm run dev
```

### Run (Desktop Mode)
```bash
# Builds frontend, then launches pywebview wrapper
run_web_desktop.bat
```

### Build Frontend
```bash
cd frontend
npm run build    # tsc -b && vite build → frontend/dist/
```

### Run Backend Tests
```bash
cd backend && .venv\Scripts\python.exe -m pytest tests/ -q
```

## Architecture

### Backend (`backend/`)
FastAPI application served by uvicorn. Entry point: `backend/main.py` (`create_app()`).

```
backend/
├── main.py                  # FastAPI app factory, middleware, static file serving
├── routers/                 # API route handlers (14 routers)
│   ├── tts.py               # TTS synthesis + voice listing
│   ├── documents.py         # PDF extraction/polishing (split from tts.py)
│   ├── chat.py              # LLM chat (streaming + non-streaming)
│   ├── voice_chat.py        # Realtime voice WebSocket endpoint
│   ├── translate.py         # Translation
│   ├── transcription.py     # ASR / audio transcription
│   ├── audio_overview.py    # Audio analysis/overview
│   ├── audio_agent.py       # Audio agent runs
│   ├── voices.py            # Voice management (design/clone)
│   ├── settings.py          # App settings API
│   ├── auth.py              # Authentication
│   ├── evermem.py           # EverMem memory service
│   └── agent_runs.py        # Agent run history
├── services/                # Business logic
│   ├── tts_service.py       # TTS engine abstraction (9 engines)
│   ├── llm_service.py       # Multi-provider LLM client
│   ├── realtime_voice_service.py    # Facade composing 4 provider mixins
│   ├── realtime_google_provider.py  # Google Gemini Live
│   ├── realtime_dashscope_provider.py # DashScope Qwen-Omni (SDK)
│   ├── realtime_openai_provider.py  # OpenAI Realtime (WebSocket)
│   ├── realtime_qwen_audio_provider.py # Qwen-Audio (raw WebSocket)
│   ├── transcription_service.py     # Multi-provider ASR
│   ├── voice_agent_tools.py         # Voice agent tool intents + executors
│   ├── evermem_helper.py    # Shared memory integration helpers
│   ├── script_parser.py     # Podcast script parsing (shared)
│   ├── config_loader.py     # JSON config access
│   └── ...                  # Other services
└── tests/                   # pytest test suite (241 tests + 89 subtests)
```

### Frontend (`frontend/`)
React 19 + Vite + TypeScript SPA. Built output in `frontend/dist/`, served by FastAPI in production.

```
frontend/src/
├── pages/                   # Page components
│   ├── ChatPage.tsx         # AI chat with streaming
│   ├── TtsPage.tsx          # TTS synthesis
│   ├── TranslatePage.tsx    # Translation
│   ├── TranscriptionPage.tsx # Audio transcription
│   ├── AudioOverviewPage.tsx # Audio analysis
│   ├── VoiceCenterPage.tsx  # Voice management hub
│   ├── VoiceDesignPage.tsx  # Voice design
│   ├── VoiceClonePage.tsx   # Voice cloning
│   └── SettingsPage.tsx     # Settings
├── api.ts                   # API client
├── components/              # Reusable UI components
└── hooks/                   # React hooks
```

### Key Patterns

**ApiClient / LLMService** (`backend/services/llm_service.py`)
- Async httpx-based client supporting OpenAI-compatible, Gemini, and DashScope APIs
- Streaming responses via SSE for chat

**RealtimeVoiceService** (`backend/services/realtime_voice_service.py`)
- Facade composing 4 provider mixins via multiple inheritance
- Shared infrastructure: `_handle_common_client_command()` (config/ping/interruption/stop), `_decide_interruption()`, `_finalize_realtime_turn()`, `_tool_event_sender()`
- Each provider mixin implements transport-specific logic (audio forwarding, session config, tool-call lifecycle)

**TtsService** (`backend/services/tts_service.py`)
- 9-engine dispatch: Edge, Qwen Flash, MiniMax, OpenAI, ElevenLabs, ChatTTS, GPT-SoVITS, Xiaomi, Azure
- Content-hash cache with atomic writes and eviction (500 files / 72h)

**Config** (`backend/services/config_loader.py`)
- JSON-based config with mtime-based incremental reload
- API keys, model selections, UI preferences

## Configuration

Config file `config.json` is created automatically on first run (not in source control). Structure:
- `api_keys.*` - API keys for providers
- `api_urls.*` - Custom API endpoints
- `default_models.*` - Model selections per provider
- `shortcuts.*` - Global hotkeys

## Dependencies

### Backend
Key packages: FastAPI, uvicorn, httpx, edge-tts, google-genai, dashscope, pydub, pypdf, azure-cognitiveservices-speech

External: ffmpeg binaries (for audio processing)

### Frontend
React 19, Vite, TypeScript, lucide-react, @lobehub/icons

## Language

The codebase uses English for code but Chinese for UI strings and some comments. Translation files are in `resources/`.
