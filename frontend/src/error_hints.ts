const EXACT_HINTS: Record<string, string[]> = {
  AUTH_TOKEN_MISSING: [
    "Set token in client env (VITE_API_TOKEN) and retry.",
    "Ensure request includes Authorization: Bearer <token>."
  ],
  AUTH_TOKEN_INVALID: [
    "Check token value and remove trailing spaces.",
    "Verify backend token source: VOICESPIRIT_API_TOKEN or config auth_settings.api_token."
  ],
  AUTH_ADMIN_TOKEN_MISSING: [
    "Settings write requires admin token.",
    "Set VITE_API_ADMIN_TOKEN (or send Authorization with admin token)."
  ],
  AUTH_ADMIN_TOKEN_INVALID: [
    "Use admin token (not normal API token) for settings write.",
    "Verify VOICESPIRIT_ADMIN_TOKEN / auth_settings.admin_token on backend."
  ],
  AUDIO_MERGE_STRATEGY_INVALID: [
    "Use merge strategy: auto, pydub, ffmpeg, concat.",
    "Set strategy to auto if dependency status is unknown."
  ],
  AUDIO_MERGE_PYDUB_FAILED: [
    "Install pydub in backend venv.",
    "Switch to auto or concat and retry."
  ],
  AUDIO_MERGE_FFMPEG_FAILED: [
    "Install ffmpeg and ensure ffmpeg -version works in backend runtime.",
    "Switch to auto or concat as fallback."
  ],
  AUDIO_MERGE_ALL_FAILED: [
    "Try merge strategy concat for immediate fallback.",
    "Repair ffmpeg/pydub dependencies in backend runtime."
  ],
  AUDIO_SEGMENT_SYNTHESIS_FAILED: [
    "Check provider API key/model in Settings.",
    "Try different voices and retry synthesis."
  ],
  AUDIO_OVERVIEW_AUDIO_MISSING: [
    "Run Synthesize Audio first.",
    "Then load/download the audio again."
  ],
  AUDIO_OVERVIEW_AUDIO_FILE_NOT_FOUND: [
    "Audio path is stale or file was removed.",
    "Re-run synthesis to regenerate output."
  ],
  INVALID_API_KEY_ENCODING: [
    "Ensure API Key only contains ASCII characters (letters, numbers, hyphen, underscore).",
    "Remove Chinese characters or placeholder text pasted into the API key field."
  ],
  INVALID_BASE_URL_ENCODING: [
    "Ensure Base URL only contains valid URL characters.",
    "Remove non-ASCII or Chinese text from the Base URL field."
  ],
  INVALID_HEADER_ENCODING: [
    "API Key or Base URL contains non-ASCII characters.",
    "Check for Chinese characters or full-width punctuation in Settings."
  ],
  FETCH_MODELS_FAILED: [
    "Check if API Key or Base URL field contains invalid Chinese characters or instructions.",
    "Verify provider endpoint URL and network connectivity."
  ],
  TAVUS_NOT_CONFIGURED: [
    "Open the Video PAL page and enter your Tavus API Key.",
    "Or set the TAVUS_API_KEY environment variable on the backend."
  ],
  TAVUS_PAL_ID_MISSING: [
    "Select a PAL from the dropdown or enter a PAL ID manually.",
    "Or set the TAVUS_PAL_ID environment variable on the backend."
  ],
  TAVUS_AUTH_REJECTED: [
    "Check that your Tavus API Key is correct and active.",
    "Create a new key at platform.tavus.io if needed."
  ]
};

const PREFIX_HINTS: Array<{ prefix: string; hints: string[] }> = [
  {
    prefix: "TRANSCRIPTION_",
    hints: [
      "Check ASR provider API Key / Access Token / App ID in Settings → Doubao.",
      "For Doubao ASR (Volcengine), ensure your API Key or Access Token is valid and has Doubao ASR service activated."
    ]
  },
  {
    prefix: "CHAT_PROVIDER_ERROR",
    hints: [
      "Check provider API key / endpoint / model.",
      "Retry after confirming outbound network from backend."
    ]
  },
  {
    prefix: "TRANSLATE_PROVIDER_ERROR",
    hints: [
      "Check translation provider settings in Settings tab.",
      "Retry with another model/provider if available."
    ]
  },
  {
    prefix: "SETTINGS_",
    hints: [
      "Verify payload field names and value types.",
      "If admin token is enabled, use VITE_API_ADMIN_TOKEN."
    ]
  },
  {
    prefix: "VOICE_",
    hints: [
      "Check qwen voice provider key and service status.",
      "Retry with simpler name/input and inspect backend logs."
    ]
  },
  {
    prefix: "TTS_SPEAK_DEPENDENCY_ERROR",
    hints: [
      "Check engine credentials (API Key / Access Token) in Settings.",
      "Verify engine status, network access, or backend runtime logs."
    ]
  },
  {
    prefix: "TTS_",
    hints: [
      "Verify input text/voice/rate fields.",
      "Check backend logs for detailed TTS failure reason."
    ]
  },
  {
    prefix: "AUDIO_SCRIPT_GENERATE_PROVIDER_ERROR",
    hints: [
      "Check LLM provider config and model name.",
      "Retry with default model in Settings."
    ]
  },
  {
    prefix: "AUDIO_OVERVIEW_",
    hints: [
      "Ensure podcast id exists and script content is valid.",
      "Refresh podcast list and retry operation."
    ]
  },
  {
    prefix: "AUDIO_SYNTHESIZE_",
    hints: [
      "Retry with merge strategy auto or concat.",
      "Check backend logs for synthesis stack trace."
    ]
  },
  {
    prefix: "TAVUS_",
    hints: [
      "Check Tavus API Key in the Video PAL page.",
      "Verify network connectivity to tavusapi.com and retry."
    ]
  }
];

export function parseErrorCode(message: string): string {
  const text = String(message || "").trim();
  const matched = text.match(/^([A-Z0-9_]+)\s*:/);
  if (matched) {
    return matched[1];
  }
  const rawCode = text.match(/\b([A-Z][A-Z0-9_]{5,})\b/);
  return rawCode ? rawCode[1] : "";
}

export function parseRequestId(message: string): string {
  const text = String(message || "");
  const matched = text.match(/request_id:\s*([A-Za-z0-9_-]+)/);
  return matched ? matched[1] : "";
}

export function buildErrorHints(message: string): string[] {
  const text = String(message || "");
  if (/api\s*key.*(not configured|未配置)/i.test(text)) {
    return [
      "Open Settings and fill the API Key for the selected TTS provider.",
      "Save settings, then retry synthesis with the same voice."
    ];
  }
  const code = parseErrorCode(message);
  if (!code) {
    return [];
  }
  if (EXACT_HINTS[code]) {
    return EXACT_HINTS[code];
  }
  for (const item of PREFIX_HINTS) {
    if (code.startsWith(item.prefix)) {
      return item.hints;
    }
  }
  return [];
}
