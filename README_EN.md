# Echo

**A batteries-included, local-first realtime voice AI assistant** — full-duplex voice chat, TTS, voice cloning, and live transcription in one app.

[English](README_EN.md) | [简体中文](README.md) | [日本語](README.ja.md)

---

## What is this?

Echo is a **ready-to-use voice AI desktop app** (FastAPI + React, runs in your browser or a desktop window).

[LiveKit Agents](https://github.com/livekit/agents), [Pipecat](https://github.com/pipecat-ai/pipecat), and [TEN Framework](https://github.com/TEN-framework/ten-framework) are excellent — but they are **frameworks for developers**: you get building blocks and write the agent, integrations, and UI yourself.

**Echo is the finished product**: download, paste an API key, start talking. It also natively supports Chinese voice providers (Qwen-Omni, Doubao full-duplex, Xiaomi, MiniMax…), which those frameworks barely cover.

## Features

### 🎙️ Realtime full-duplex voice chat
- Talk and listen simultaneously, interrupt anytime (barge-in), VAD + smart interruption handling
- Providers: OpenAI Realtime · Google Gemini Live · Qwen-Omni / Qwen-Audio (DashScope) · Doubao full-duplex · GLM-4 Voice · Cartesia · Gradium · PersonaPlex (local English-speaking practice partner)
- Voice tool calling, long-term memory (EverMem), live session config updates

### 🔊 TTS (13 engines)
Edge TTS · Qwen TTS · MiniMax · OpenAI · ElevenLabs · ChatTTS · GPT-SoVITS · Xiaomi · Azure · Doubao · Cartesia · Gradium · Soniox — with content-hash caching so nothing is synthesized twice

### 🧬 Voice Center
Voice design (text-to-voice) and voice cloning from a short sample

### 📝 Transcription
- Long audio/video transcription: automatic ffmpeg chunking, audio track extraction from video — no single-file length limits
- Live microphone transcription (Qwen-Audio-3.0-ASR-Flash-Streaming / Fun-ASR-Realtime)
- Synced subtitle player, SRT/VTT export, batch management, one-click save to memory

### 🎧 More
Podcast / multi-speaker dialogue generation · translation (incl. realtime bidirectional interpreting) · AI chat (DeepSeek / OpenRouter / Groq / SiliconFlow / Google Gemini / Qwen / Ollama, plus custom providers) · PDF reading & polishing · realtime video personas via Tavus

## Quick Start

**Requirements**: Python 3.10+ · Node.js 20+ (Vite 7 needs ≥ 20.19) · ffmpeg

```bash
# Windows one-click (backend + frontend dev servers)
run_web.bat

# Desktop mode (builds frontend + pywebview window)
run_web_desktop.bat
```

Manual (works on macOS / Linux too):

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

Desktop troubleshooting: `python run_web_desktop.py --check`

### Optional features

```bash
# Local open-source TTS (ChatTTS / GPT-SoVITS clone transcription)
pip install -r backend/requirements-local-tts.txt

# PersonaPlex realtime English-practice provider (model runs as a separate moshi.server process)
pip install -r backend/requirements-personaplex.txt
```

## Architecture

```
backend/    FastAPI · 14 routers · service layer (composable realtime providers / 13-engine TTS dispatch / multi-provider LLM)
frontend/   React 19 + Vite + TypeScript SPA (FastAPI serves dist/ in production)
```

- **RealtimeVoiceService**: facade composing provider mixins — shared interruption logic, turn finalization, and tool-event dispatch; each provider implements only its transport
- **TtsService**: engine dispatch + content-hash cache (atomic writes, size-based eviction)
- **ConfigLoader**: JSON config with mtime-based hot reload

## Testing

```bash
cd backend && python -m pytest tests/ -q
cd frontend && npm run test:run
```

## FAQ

**Which API keys do I need?**
Depends on the features: text chat plus Edge TTS works with zero keys; realtime voice and cloning need a key for whichever provider you pick. Everything stays in a local `config.json`.

**Does it run on macOS / Linux?**
Yes. The manual commands are cross-platform; the `.bat` scripts are just Windows shortcuts.

**Does my data leave my machine?**
No. Config, session history, and transcripts live locally (SQLite + local files). Only the cloud APIs you call see your requests.

## Roadmap

- [ ] Semantic turn detection (SmartTurn-style)
- [ ] More realtime providers
- [ ] One-click installers

## License

[MIT](LICENSE)

---

> Fun fact: Echo is also Earthshaker's ultimate in DOTA2 (Echo Slam) — the more enemies, the louder the echo. 🎯
