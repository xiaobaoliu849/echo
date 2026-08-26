# Echo

**A batteries-included, local-first realtime voice AI assistant** — full-duplex voice chat, TTS, voice cloning, and live transcription in one app.

中文 | [English](README_EN.md)

---

## What is this?

Echo is a **ready-to-use voice AI desktop app** (FastAPI + React, runs in your browser or a desktop window).

[LiveKit Agents](https://github.com/livekit/agents), [Pipecat](https://github.com/pipecat-ai/pipecat), and [TEN Framework](https://github.com/TEN-framework/ten-framework) are excellent — but they are **frameworks for developers**: you get building blocks and write the agent, integrations, and UI yourself.

**Echo is the finished product**: download, paste an API key, start talking. It also natively supports Chinese voice providers (Qwen-Omni, Doubao full-duplex, Xiaomi, MiniMax…), which those frameworks barely cover.

## Features

### 🎙️ Realtime full-duplex voice chat
- Talk and listen simultaneously, interrupt anytime (barge-in), VAD + smart interruption handling
- Providers: OpenAI Realtime · Google Gemini Live · DashScope Qwen-Omni · Doubao full-duplex · GLM4Voice · PersonaPlex (English speaking practice)
- Voice tool calling, long-term memory (EverMem), live session config updates

### 🔊 TTS (9+ engines)
Edge TTS · Qwen TTS · MiniMax · OpenAI · ElevenLabs · ChatTTS · GPT-SoVITS · Xiaomi · Azure · Cartesia — with content-hash caching so nothing is synthesized twice

### 🧬 Voice Center
Voice design (text-to-voice) and voice cloning from a short sample

### 📝 Transcription
- Long audio/video transcription: automatic ffmpeg chunking, audio track extraction from video — no single-file length limits
- Live microphone transcription (Qwen-ASR-Flash-Streaming)
- Synced subtitle player, SRT/VTT export, batch management, one-click save to memory

### 🎧 More
Podcast / multi-speaker dialogue generation · translation · AI chat (DeepSeek / OpenRouter / Groq / SiliconFlow / Gemini / DashScope / Ollama) · PDF reading & polishing

## Quick Start

**Requirements**: Python 3.10+ · Node.js 18+ · ffmpeg

```bash
# Windows one-click (backend + frontend dev servers)
run_web.bat

# Desktop mode (builds frontend + pywebview window)
run_web_desktop.bat
```

Manual:

```bash
# Backend
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Frontend (second terminal)
cd frontend
npm install
npm run dev
```

A `config.json` is created on first run — open the Settings page and add your provider API keys.

## Architecture

```
backend/    FastAPI · 14 routers · service layer (composable realtime providers / 9-engine TTS dispatch / multi-provider LLM)
frontend/   React 19 + Vite + TypeScript SPA (FastAPI serves dist/ in production)
```

- **RealtimeVoiceService**: facade composing provider mixins — shared interruption logic, turn finalization, and tool-event dispatch; each provider implements only its transport
- **TtsService**: engine dispatch + content-hash cache (atomic writes, size-based eviction)
- **ConfigLoader**: JSON config with mtime-based hot reload

```bash
# Tests
cd backend && python -m pytest tests/ -q
cd frontend && npm run test:run
```

## Roadmap

- [ ] Semantic turn detection (SmartTurn-style)
- [ ] More realtime providers
- [ ] One-click installers

## License

[MIT](LICENSE)

---

> Fun fact: Echo is also Earthshaker's ultimate in DOTA2 (Echo Slam) — the more enemies, the louder the echo. 🎯
