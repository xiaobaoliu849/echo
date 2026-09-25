---
name: video-showcase-generator
description: >-
  Automated screen recording remixer and Remotion video generator. Transforms long
  raw desktop screen captures into punchy 30-60 second promo videos with synchronized
  captions, animated feature badges, audio normalization, and cinematic crossfades.
---

# Video Showcase Generator Skill

Use this skill whenever you need to turn raw application screen recordings into high-converting, professional 30-60 second demo/promo videos for Echo or similar desktop applications.

---

## The 4-Beat Promo Structure (30 Seconds)

To capture immediate attention on social platforms (Twitter/X, Bilibili, YouTube Shorts, WeChat Channels):

1. **Beat 1: The Hook (0 - 5s)**
   - Display core model or flagship feature badge (e.g. `Echo × Gemini 3.8 Live | Extended Thinking`).
   - Feature user prompt or immediate question triggering the capability.
2. **Beat 2: The Magic / Tool Call (5 - 12s)**
   - Show the agent calling tools dynamically (`render_canvas`, TTS, code generation).
   - Show dynamic transition from raw output to live rendered UI.
3. **Beat 3: Interactive Sandbox (12 - 22s)**
   - Close-up or direct interaction: user clicking buttons, typing input, observing live voice response.
   - Prove that latency is near-instant and bidirectional.
4. **Beat 4: Callout & Outro (22 - 30s)**
   - Echo value proposition (`Natural Voice • Deep Thinking • Live Interactive Canvas`).
   - Clean brand card with slogan and GitHub/download link.

---

## Pipeline & Tooling

### 1. Audio Transcription & Keyframe Mining
Use `faster_whisper` to quickly detect speech intervals, questions, and responses:
```python
from faster_whisper import WhisperModel
model = WhisperModel('tiny', device='cpu', compute_type='int8')
segments, _ = model.transcribe(audio_wav)
```

### 2. High-Performance Assembly (FFmpeg)
Use the included project script `scripts/remix_demo_video.py`:
- **Trimming**: Frame-accurate extraction with `-ss` and `-t`.
- **Transitions**: Native GPU/CPU crossfade with `xfade=transition=fade:duration=0.5` and audio crossfade with `acrossfade=d=0.5`.
- **Audio Mastering**: EBU R128 loudness normalization via `loudnorm=I=-16:TP=-1.5:LRA=11`.
- **Broadcast ASS Subtitles**: Dual English + Chinese subtitles with dark obsidian glass backdrops and accent highlights.

### 3. Remotion React Architecture
For programmatic motion graphics, Remotion compositions are structured as:
```tsx
import { Composition, Sequence } from 'remotion';
import { ScreenPlayer } from './ScreenPlayer';
import { TopPill } from './TopPill';
import { Subtitles } from './Subtitles';

export const PromoVideo = () => {
  return (
    <>
      <ScreenPlayer src="video.mp4" />
      <TopPill text="Echo × Gemini 3.8 Live" />
      <Subtitles />
    </>
  );
};
```
