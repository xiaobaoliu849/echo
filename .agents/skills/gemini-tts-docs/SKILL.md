---
name: gemini-tts-docs
description: Reference documentation, API schemas, and integration patterns for Google Gemini 3.8 Flash TTS and voice cloning/design.
---

# Gemini 3.8 Flash TTS & Voice Replication Documentation

## 1. Overview
Google introduced Gemini 3.8 Flash TTS on September 23, 2026. It is dedicated to expressive, controllable audio generation and voice creation.

### Models
- `gemini-3.8-flash-tts`: Flagship creative tier for audiobooks, acting, podcasts, and expressive dialogue.
- `gemini-3.8-flash-lite-tts`: High-throughput, cost-efficient tier for dubbing and voice agents.

## 2. Audio Generation API
- **Endpoint**: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`
- **Headers**:
  - `x-goog-api-key: <API_KEY>` or `Authorization: Bearer <API_KEY>`
  - `Content-Type: application/json`
- **Request Body**:
```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "Hello! Welcome to Echo.",
          "speech_metadata": { "style": "cheerful and friendly" }
        }
      ]
    }
  ],
  "config": {
    "response_modalities": ["AUDIO"],
    "speech_config": {
      "voice_config": {
        "prebuilt_voice_config": {
          "voice_name": "Kore"
        }
      }
    }
  }
}
```
- **Response**:
  - Returns `candidates[0].content.parts[0].inline_data.data` as base64-encoded WAV (24kHz 16-bit PCM mono).

### Prebuilt Voices
- `Puck` (Enthusiastic, Male)
- `Charon` (Deep, Authoritative, Male)
- `Kore` (Clear, Calming, Female)
- `Fenrir` (Bold, Resonant, Male)
- `Aoede` (Soft, Expressive, Female)
- `Leda` (Warm, Engaging, Female)
- `Orus` (Crisp, Direct, Male)
- `Zephyr` (Gentle, Friendly, Neutral)

## 3. Voice Management API (/v1beta/voices)
- **Base URL**: `https://generativelanguage.googleapis.com/v1beta/voices`

### Voice Design (`type="prompted"`)
Creates a new custom vocal persona from natural language prompts.
- **Method**: `POST /v1beta/voices`
```json
{
  "store": true,
  "voice": {
    "model": "gemini-3.8-flash-tts",
    "type": "prompted",
    "display_name": "Warm Astronomer",
    "description": "A calm, thoughtful British astronomer with gentle pacing."
  }
}
```
- **Response**:
  - `voice_id`: e.g. `voice_gemini_...`
  - `sample_audio`: base64-encoded audio WAV preview

### Voice Replication / Clone (`type="replicated"`)
Replicates a speaker's voice from reference audio.
- **Method**: `POST /v1beta/voices`
```json
{
  "type": "replicated",
  "store": true,
  "replicated": {
    "source_audio": "<BASE64_AUDIO>",
    "consent_audio": "<BASE64_AUDIO>"
  }
}
```

### List Voices
- **Method**: `GET /v1beta/voices`

### Delete Voice
- **Method**: `DELETE /v1beta/voices/{voice_id}`
