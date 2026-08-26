# AGENTS.md

This file describes the current, tracked Echo architecture and the verification expected for repository changes.

## Project overview

Echo is a local-first voice and AI desktop application. The maintained application is a React/TypeScript frontend backed by FastAPI. The desktop shell is PyWebView and serves the same built frontend through the FastAPI process.

The old PySide6 application may still exist in local, ignored folders on some workstations, but it is not part of the tracked application and must not be treated as the current architecture.

## Commands

### Web development

```bat
run_web.bat
```

This starts FastAPI on `http://127.0.0.1:8000` and Vite on `http://127.0.0.1:5173`.

Equivalent manual commands:

```bash
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

cd frontend
npm run dev
```

### Desktop application

```bat
run_web_desktop.bat
```

The launcher installs desktop dependencies when needed, builds the frontend, starts the backend, and opens the application in PyWebView.

Useful diagnostics:

```bash
python run_web_desktop.py --check
python run_web_desktop.py --export-diagnostics
```

### Verification

```bash
cd frontend
npm run test:run
npm run build

cd backend
python -m pytest -q
```

Run the focused tests while iterating, then run the full frontend tests, frontend production build, and backend tests before handing off changes that cross application boundaries.

## Architecture

### Entry points

- `frontend/src/main.tsx` mounts the React application.
- `frontend/src/App.tsx` owns top-level state, navigation, and page composition.
- `backend/main.py` creates the FastAPI app, installs middleware, mounts API routers, and serves `frontend/dist` for desktop use.
- `run_web_desktop.py` manages the backend process, desktop runtime state, diagnostics, and PyWebView window.

### Frontend

```text
frontend/src/
├── api.ts              # API contracts and HTTP/WebSocket client functions
├── App.tsx             # application composition and navigation
├── appConfig.ts        # navigation/model/UI configuration
├── components/         # reusable UI and podcast components
├── hooks/              # feature state and side effects
├── pages/              # chat, translation, voice, transcription, and podcast UI
├── test/               # test factories, setup, and dependency mocks
├── types/              # shared UI types
└── styles.css          # current global style sheet
```

Important patterns:

- Feature behavior lives primarily in hooks such as `useVoiceChat`, `useChat`, and `useAudioOverview`.
- `ChatPage` is the primary text and realtime voice conversation surface.
- The realtime voice client uses WebSocket events and must preserve interruption, replay, ordering, and cleanup semantics.
- Vitest and Testing Library cover hooks, pages, components, and application interactions.

### Backend

```text
backend/
├── main.py             # FastAPI application factory
├── routers/            # HTTP and WebSocket transport layer
├── services/           # provider integrations and business logic
├── tests/              # pytest suite
├── requirements.txt
└── requirements-local-tts.txt
```

Important patterns:

- Routers should remain thin and delegate provider/business behavior to services.
- `services/realtime_voice_service.py` owns the realtime provider session lifecycle.
- `services/voice_agent_session_repository.py` persists canonical voice timelines and metrics.
- `services/agent_run_repository.py` and `agent_run_service.py` manage durable agent runs.
- Runtime configuration and user data are local files and must not be committed.

## Repository hygiene

- Never commit virtual environments, build output, logs, databases, generated TypeScript build metadata, temporary audio, or local configuration.
- Do not add generated patches or one-off debugging scripts to `backend/`.
- Keep diagnostics and historical metrics out of the primary conversation UI unless they directly help the end user complete a task.
- Preserve provider-neutral contracts. Provider-specific behavior belongs behind service or adapter boundaries.
- Large realtime files require incremental extraction with behavior-preserving tests; do not combine a major lifecycle refactor with unrelated UI work.

## Language

Code identifiers are English. The product UI is bilingual through `useI18n`; user-facing strings should provide both Chinese and English variants where the surrounding code does.
