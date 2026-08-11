# Live translation with Gemini Live API

The Gemini Live API supports low-latency, real-time speech to speech translation between 70+ languages using the [`gemini-3.5-live-translate-preview`](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-live-translate-preview) model. By configuring the Live API with translation settings, you can stream audio in one language and receive translated audio output in another language, enabling seamless real-time voice-to-voice translation.
[Try the Live Translate in Google AI Studio](https://aistudio.google.com/live?model=gemini-3.5-live-translate-preview) [Clone the example app from GitHub](https://github.com/google-gemini/gemini-live-api-examples) [Use coding agent skills](https://ai.google.dev/gemini-api/docs/coding-agents#gemini-live-api-dev)

## Live Agent vs. Live Translation

While both use the Live API, the mental model for Live Translation is different from conversational real-time agent interactions.

| Live Agent | Live Translation |
|---|---|
| **The model acts as an assistant.** It listens, reasons, and takes actions on your behalf. | **The model acts as an interpreter.** It behaves as a real-time translator pipeline. |
| **Uses turn-based interactions.** Relies on pauses, intent detection, and handles interruptions. | **Uses continuous stream processing.** Translates as the speaker talks without waiting for turns. |
| **Supports tools and agents.** Native support for function calling, Google Search, and instructions. | **Supports translation only.** Pure low-latency translation; no support for tools or instructions. |
| **Fully multimodal.** Supports text, audio, video, and image inputs. | **Audio restricted.** Input is limited to audio to ensure strict real-time latency thresholds. |
| **Granular configuration.** Uses generation, speech, tools, and system instructions. | **Simplified configuration.** Set `target_language_code` and toggles like `echo_target_language`. |

## Get started

The following examples demonstrate how to initialize a client and connect to the Live API with a translation configuration.

### Python

    import asyncio
    from google import genai
    from google.genai import types

    client = genai.Client()

    model = "gemini-3.5-live-translate-preview"
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        translation_config=types.TranslationConfig(
            target_language_code="pl",
            echo_target_language=True
        )
    )

    async def main():
        async with client.aio.live.connect(model=model, config=config) as session:
            print("Session started with translation")
            # Start receiving the translated audio stream
            async for response in session.receive():
                if response.server_content:
                    if response.server_content.input_transcription:
                        print(f"Input transcript: {response.server_content.input_transcription.text}")
                    if response.server_content.output_transcription:
                        print(f"Output transcript: {response.server_content.output_transcription.text}")
                    if response.server_content.model_turn:
                        for part in response.server_content.model_turn.parts:
                            if part.inline_data:
                                audio_data = part.inline_data.data
                                # Play or process the translated audio chunk
                                print(f"Received audio chunk ({len(audio_data)} bytes)")

    if __name__ == "__main__":
        asyncio.run(main())

### JavaScript

    import { GoogleGenAI, Modality } from '@google/genai';

    const ai = new GoogleGenAI({});
    const model = 'gemini-3.5-live-translate-preview';
    const config = {
        responseModalities: [Modality.AUDIO],
        inputAudioTranscription: {},
        outputAudioTranscription: {},
        translationConfig: {
            targetLanguageCode: 'pl',
            echoTargetLanguage: true
        }
    };

    async function main() {
      const session = await ai.live.connect({
        model: model,
        config: config,
        callbacks: {
          onopen: () => console.debug('Opened'),
          onmessage: (message) => {
            const content = message.serverContent;
            if (content?.inputTranscription) {
              console.log('Input transcript:', content.inputTranscription.text);
            }
            if (content?.outputTranscription) {
              console.log('Output transcript:', content.outputTranscription.text);
            }
            if (content?.modelTurn?.parts) {
              for (const part of content.modelTurn.parts) {
                if (part.inlineData) {
                  const audioData = part.inlineData.data;
                  // Play or process the translated audio chunk (base64 encoded)
                  console.debug(`Received audio chunk (${audioData.length} bytes)`);
                }
              }
            }
          },
          onerror: (e) => console.debug('Error:', e.message),
          onclose: (e) => console.debug('Close:', e.reason),
        },
      });

      console.debug("Session started with translation");
    }

    main();

### WebSockets

    const API_KEY = "YOUR_API_KEY";
    const MODEL_NAME = "gemini-3.5-live-translate-preview";
    const WS_URL = `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key=${API_KEY}`;

    const websocket = new WebSocket(WS_URL);

    websocket.onopen = () => {
      console.log('WebSocket Connected');

      const setupMessage = {
        setup: {
          model: `models/${MODEL_NAME}`,
          generationConfig: {
            responseModalities: ['AUDIO'],
            inputAudioTranscription: {},
            outputAudioTranscription: {},
            translationConfig: {
              targetLanguageCode: 'pl',
              echoTargetLanguage: true
            }
          }
        }
      };
      websocket.send(JSON.stringify(setupMessage));
    };

    websocket.onmessage = (event) => {
      const response = JSON.parse(event.data);
      if (response.serverContent) {
        const content = response.serverContent;
        if (content.inputTranscription) {
          console.log('Input transcript:', content.inputTranscription.text, `(${content.inputTranscription.languageCode})`);
        }
        if (content.outputTranscription) {
          console.log('Output transcript:', content.outputTranscription.text, `(${content.outputTranscription.languageCode})`);
        }
        if (content.modelTurn?.parts) {
          for (const part of content.modelTurn.parts) {
            if (part.inlineData) {
              const audioData = part.inlineData.data;
              // Play or process the translated audio chunk (base64 encoded)
              console.debug(`Received audio chunk (${audioData.length} bytes)`);
            }
          }
        }
      }
    };

## Sending audio

To stream voice inputs for translation, you send raw, little-endian, 16-bit PCM audio.

- **Input audio format**: Raw 16-bit PCM at 16kHz (mono, little-endian).
- **Output audio format**: Raw 16-bit PCM at 24kHz (mono, little-endian).
- **Chunk Size and Latency**: Send audio in chunks of 100ms.

> [!NOTE]
> **Note:** Only audio input is supported for translation. Text input is not supported.

The following examples show how to send audio chunks to the session.

### Python

    # Assuming 'chunk' is your raw PCM audio bytes
    await session.send_realtime_input(
        audio=types.Blob(
            data=chunk,
            mime_type="audio/pcm;rate=16000"
        )
    )

### JavaScript

    // Assuming 'chunk' is a Buffer of raw PCM audio
    session.sendRealtimeInput({
      audio: {
        data: chunk.toString('base64'),
        mimeType: 'audio/pcm;rate=16000'
      }
    });

### WebSockets

    // Assuming 'chunk' is a Buffer of raw PCM audio
    function sendAudioChunk(chunk) {
      if (websocket.readyState === WebSocket.OPEN) {
        const audioMessage = {
          realtimeInput: {
            audio: {
              data: chunk.toString('base64'),
              mimeType: 'audio/pcm;rate=16000'
            }
          }
        };
        websocket.send(JSON.stringify(audioMessage));
      }
    }

## Configuration

To enable translation, you must specify the `translationConfig` within the `generationConfig` during the session setup.

### Setup message configuration

The `generationConfig` supports the following fields to enable transcripts:

- **`inputAudioTranscription`**: An object that, when present, enables the model to send text transcripts of the input audio.
- **`outputAudioTranscription`**: An object that, when present, enables the model to send text transcripts of the output (translated) audio.

The `translationConfig` supports the following fields:

- **`targetLanguageCode`** : The [BCP-47 language code](https://ai.google.dev/gemini-api/docs/live-api/live-translate#supported-languages) of the language you want the model to translate into (e.g., `"pl"` for Polish, `"es"` for Spanish). Defaults to `"en"`.
- **`echoTargetLanguage`** : A boolean indicating how input audio that is already in the target language should be handled. If set to `true`, the model will echo (parrot) input audio that is already in the target language. If set to `false`, the model will stay silent when the input speech is already in the target language. Defaults to `false`.

Here is an example of the setup message structure:

    "setup": {
        "model": "models/gemini-3.5-live-translate-preview",
        "generationConfig": {
          "responseModalities": [
            "AUDIO"
          ],
          "inputAudioTranscription": {},
          "outputAudioTranscription": {},
          "translationConfig": {
            "targetLanguageCode": "pl",
            "echoTargetLanguage": true
          }
        }
    }

## Ephemeral tokens for client-side applications

For client-to-server applications, you can use [ephemeral tokens](https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens) (currently in `v1alpha`) to avoid exposing your API key.

When using ephemeral tokens with Live Translation:

1. You must use the `v1alpha` endpoint.
2. **Locking configuration:** By default, you should specify the `translationConfig` in the token creation constraints on your server. This ensures the translation configuration is locked and cannot be tampered with by the client.
3. **Unlocking configuration:** If you want to be able to set the `translationConfig` on the client-side (for example, to let a user choose their own target language), you must omit it from the token creation request and set `"lock_additional_fields": []` instead. This will unlock `translationConfig` to be set on the client-side.

### Creating a constrained ephemeral token

The following examples demonstrate how to create an ephemeral token with translation constraints.

### Python

    import datetime
    from google import genai

    now = datetime.datetime.now(tz=datetime.timezone.utc)

    client = genai.Client(
        http_options={'api_version': 'v1alpha'}
    )

    token = client.auth_tokens.create(
        config = {
            'uses': 1,
            'expire_time': now + datetime.timedelta(minutes=30),
            'live_connect_constraints': {
                'model': 'gemini-3.5-live-translate-preview',
                'config': {
                    'translation_config': {
                        'target_language_code': 'pl',
                        'echo_target_language': True
                    }
                }
            },
            'http_options': {'api_version': 'v1alpha'},
        }
    )

### JavaScript

    import { GoogleGenAI } from "@google/genai";

    const client = new GoogleGenAI({});
    const expireTime = new Date(Date.now() + 30 * 60 * 1000).toISOString();

    const token = await client.authTokens.create({
        config: {
            uses: 1,
            expireTime: expireTime,
            liveConnectConstraints: {
                model: 'gemini-3.5-live-translate-preview',
                config: {
                    responseModalities: ['AUDIO'],
                    inputAudioTranscription: {},
                    outputAudioTranscription: {},
                    translationConfig: {
                        targetLanguageCode: 'pl',
                        echoTargetLanguage: true
                    }
                }
            },
            httpOptions: {
                apiVersion: 'v1alpha'
            }
        },
    });

## Limitations

- **Input Modalities**: Only audio input is supported for translation. Text input is not supported.
- **Voice Replication**: Voice replication can be inconsistent. Voices might shift after long pauses, assign the wrong gender based on how the speech starts, or get stuck on one voice during rapid multi-speaker conversations.
- **Language Detection** : Language detection struggles with heavy accents, similar languages (e.g., Spanish vs. Portuguese), or rapid language switches. **Note:** This should only impact the input transcript. Language codes and the final translation should still be accurate.
- **Background Audio**: The model is designed to filter out noise and music to produce clean speech, but not all background audio may be ignored.
- **Echo Target Language** : When `echoTargetLanguage: true`, background noise or music may introduce artifacts in the translated audio when input audio is already in the target language.

## Supported languages

The following languages are supported for Live Translation.

| Language | BCP-47 Code | Language | BCP-47 Code |
|---|---|---|---|
| Afrikaans | af | Kazakh | kk |
| Akan | ak | Khmer | km |
| Albanian | sq | Kinyarwanda | rw |
| Amharic | am | Korean | ko |
| Arabic | ar | Lao | lo |
| Armenian | hy | Latvian | lv |
| Azerbaijani | az | Lithuanian | lt |
| Basque | eu | Macedonian | mk |
| Belarusian | be | Malay | ms |
| Bengali | bn | Malayalam | ml |
| Bulgarian | bg | Marathi | mr |
| Burmese (Myanmar) | my | Mongolian | mn |
| Catalan | ca | Nepali | ne |
| Chinese (Simplified) | zh-Hans | Norwegian | no, nb |
| Chinese (Traditional) | zh-Hant | Persian | fa |
| Croatian | hr | Polish | pl |
| Czech | cs | Portuguese (Brazil) | pt-BR |
| Danish | da | Portuguese (Portugal) | pt-PT |
| Dutch | nl | Punjabi | pa |
| English | en | Romanian | ro |
| Estonian | et | Russian | ru |
| Filipino | fil | Serbian | sr |
| Finnish | fi | Sindhi | sd |
| French | fr | Sinhala | si |
| Galician | gl | Slovak | sk |
| Georgian | ka | Slovenian | sl |
| German | de | Spanish | es |
| Greek | el | Sundanese | su |
| Gujarati | gu | Swahili | sw |
| Hausa | ha | Swedish | sv |
| Hebrew | he | Tamil | ta |
| Hindi | hi | Telugu | te |
| Hungarian | hu | Thai | th |
| Icelandic | is | Turkish | tr |
| Indonesian | id | Ukrainian | uk |
| Italian | it | Urdu | ur |
| Japanese | ja | Uzbek | uz |
| Javanese | jv | Vietnamese | vi |
| Kannada | kn | Zulu | zu |

## What's next

- Read the full Live API [Capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities) guide.
- Read the [Get started with the SDK](https://ai.google.dev/gemini-api/docs/live-api/get-started-sdk) guide.
- Read the [Get started with WebSockets](https://ai.google.dev/gemini-api/docs/live-api/get-started-websocket) guide.
- Read the [Ephemeral tokens](https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens) guide for secure authentication in client-to-server applications.
- Clone the [Live API examples](https://github.com/google-gemini/gemini-live-api-examples) from GitHub.