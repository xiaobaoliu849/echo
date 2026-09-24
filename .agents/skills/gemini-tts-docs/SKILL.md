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
- **REST Request Body** (`generateContent`; SDK calls use a separate `config` argument):
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
  "generationConfig": {
    "responseModalities": ["AUDIO"],
    "speechConfig": {
      "voiceConfig": {
        "prebuiltVoiceConfig": {
          "voiceName": "Kore"
        }
      }
    }
  }
}
```
- **Response**:
  - Returns `candidates[0].content.parts[0].inlineData.data` as base64-encoded WAV (24kHz 16-bit PCM mono).

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
- **Base Endpoint**: `https://generativelanguage.googleapis.com/v1beta/voices`

### Voice Design (`type="prompted"`)
Creates a new custom vocal persona from natural language prompts.
- **Method**: `POST /v1beta/voices`
- **Request Body**:
```json
{
  "store": true,
  "voice": {
    "model": "gemini-3.8-flash-tts",
    "type": "prompted",
    "display_name": "Warm Astronomer",
    "prompted": {
      "input": "A calm, thoughtful British astronomer with gentle pacing."
    }
  }
}
```
- **Response**:
  - `id`: Unique voice ID, e.g. `voice_d9pmbibq9eoe`
  - `sample_audio`: Object `{ "mime_type": "audio/x-wav", "data": "<BASE64_AUDIO>" }` (24kHz 16-bit PCM mono with SynthID & C2PA metadata)

### Voice Replication / Clone (`type="replicated"`)
Replicates a speaker's voice from reference audio.
- **Method**: `POST /v1beta/voices`
- **Requirement**: Google enforces a mandatory verbal consent check. The audio (in `consent_audio` or both clips) must include the speaker clearly reciting:
  > *"I am the owner of this voice and I consent to Google using this voice to create a synthetic voice model."*
- **Request Body**:
```json
{
  "store": true,
  "voice": {
    "model": "gemini-3.8-flash-tts",
    "type": "replicated",
    "display_name": "Cloned Speaker",
    "replicated": {
      "source_audio": {
        "mime_type": "audio/wav",
        "data": "<BASE64_AUDIO>"
      },
      "consent_audio": {
        "mime_type": "audio/wav",
        "data": "<BASE64_AUDIO>"
      }
    }
  }
}
```
- **Response**:
  - `id`: e.g. `voice_...`

### List Voices
- **Method**: `GET /v1beta/voices`
- **Response**: List of voice objects containing `id`, `type`, `display_name`, `model`, etc.

### Delete Voice
- **Method**: `DELETE /v1beta/voices/{voice_id}`
