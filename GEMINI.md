# GEMINI.md - Echo 2.0 Project Context

## Project Overview
Echo 2.0 is a comprehensive AI-powered audio and text assistant. It is a modern **FastAPI + React Web/Desktop Application** (with desktop PyWebView shell). The project focuses on multi-engine Text-to-Speech (TTS), LLM-based Chat/Translation, and advanced Voice Design/Cloning.

### Key Features
- **Multi-Engine TTS:** Supports Edge TTS, Google TTS, and Qwen TTS with fine-grained control over voice, rate, and caching.
- **AI Chat & Translation:** OpenAI-compatible LLM integration (DeepSeek, OpenRouter, Groq, SiliconFlow, DashScope) with SSE streaming support.
- **Voice Design & Clone:** Specialized integration with Alibaba DashScope (Qwen) for generating and cloning custom voices.
- **Audio Overview (Podcasts):** Automated script generation followed by multi-voice synthesis and merging (via Pydub/FFmpeg) to create podcasts.
- **Structured Error Handling:** A unified error system across backend (FastAPI) and frontend (React) using `code/message/meta` structures and `request_id` tracing.
- **Authentication:** Optional Bearer token authentication for write-access API endpoints.

---

## Technical Stack

### Backend (Web & Core)
- **Framework:** FastAPI (Web), PySide6 (Desktop).
- **Audio Processing:** `edge-tts`, `pydub`, `ffmpeg`.
- **Database:** SQLite (for podcasts and session history).
- **Configuration:** `config.json` managed via `app/core/config.py` and `backend/services/settings_service.py`.
- **Tracing & Logging:** Global `X-Request-ID` tracing, structured JSON logging for requests and errors.

### Frontend (Web)
- **Framework:** React 19, Vite, TypeScript.
- **Testing:** Vitest with JSDOM and React Testing Library.
- **UI Architecture:** Tab-based navigation (TTS, Chat, Translate, Voice Design, Voice Clone, Audio Overview, Settings).
- **Error Observability:** `ErrorNotice` component with actionable hints, diagnostic export, and Markdown issue template generation.

---

## Building and Running

### Desktop Application
```bash
# Recommended environment: Conda (whisperx) or standard Python 3.10+
python main_new.py
```
- **Build Scripts:** `build.bat`, `package.bat` (uses PyInstaller).

### Web Version (Migration Phase B)
**Backend:**
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```
- **Tests:** `cd backend && .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`

**Frontend:**
```bash
cd frontend
npm install
npm run dev     # Development (http://localhost:5173)
npm run build   # Production build
npm run test    # Run vitest
```

---

## Development Conventions

### Error Handling (Mandatory)
All new API endpoints MUST return structured errors in case of failure:
```json
{
  "detail": {
    "code": "ERROR_CODE_CONSTANT",
    "message": "User friendly message",
    "meta": { "extra": "data", "request_id": "..." }
  }
}
```
Refer to `backend/docs/error_codes_catalog.md` for existing codes.

### API Tracing
- All requests should include or will be assigned an `X-Request-ID`.
- This ID must be propagated to logs and error responses to facilitate troubleshooting.

### Configuration
- Configuration is centralized in `config.json`.
- In the desktop app, use `ConfigManager`.
- In the web backend, use `SettingsService`.

### Frontend Components
- Use `frontend/src/components/ErrorNotice.tsx` for displaying API errors.
- Add new error hints to `frontend/src/error_hints.ts`.

---

## Key Directories
- `app/`: Desktop application source (UI & Core).
- `backend/`: FastAPI backend implementation.
- `frontend/`: React frontend implementation.
- `utils/`: Shared utilities for audio and TTS handling.
- `resources/`: Assets (icons, themes).
- `backup_before_cleanup/`: Legacy code and assets.
