from __future__ import annotations

import copy
from typing import Any

from .config_loader import BackendConfig, DEFAULT_BASE_URLS, PROVIDER_KEY_MAP

SETTINGS_PROVIDERS = tuple(PROVIDER_KEY_MAP.keys())
MEMORY_SETTINGS_ALIASES = {
    "url": "api_url",
    "key": "api_key",
    "scopeId": "scope_id",
    "tempSession": "temporary_session",
    "sceneChat": "remember_chat",
    "sceneVoiceChat": "remember_voice_chat",
    "sceneTranscription": "remember_recordings",
    "scenePodcast": "remember_podcast",
    "sceneTts": "remember_tts",
    "storeTranscriptFulltext": "store_transcript_fulltext",
}
MEMORY_SETTINGS_BOOL_KEYS = {
    "enabled",
    "remember_chat",
    "remember_voice_chat",
    "remember_recordings",
    "remember_podcast",
    "remember_tts",
    "store_transcript_fulltext",
    "temporary_session",
}
MEMORY_SETTINGS_STR_KEYS = {"api_url", "api_key", "scope_id"}

# Sentinel returned by GET /api/settings instead of stored credentials, and
# accepted on PUT as "keep the existing value". A user is never expected to
# type this literally; anything else (including "") is written verbatim.
MASKED_SECRET = "__MASKED__"

_SECRET_NESTED_KEYS: dict[str, set[str]] = {
    "minimax": {"api_key"},
    "xiaomi": {"api_key"},
    "memory_settings": {"api_key"},
    "transcription_settings": {"s3_secret_access_key"},
    "auth_settings": {"api_token", "admin_token"},
}


def _is_secret_field(section: str, key: str) -> bool:
    if section == "api_keys":
        return key.endswith("_api_key") or key in {
            "doubao_access_token",
            "doubao_websearch_api_key",
        }
    return key in _SECRET_NESTED_KEYS.get(section, set())


def _mask_secrets(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``data`` with every non-empty credential replaced by
    MASKED_SECRET, safe to return from GET /api/settings."""
    masked = copy.deepcopy(data)
    for section in set(list(masked.keys()) + list(_SECRET_NESTED_KEYS)):
        value = masked.get(section)
        if not isinstance(value, dict):
            continue
        for key in list(value.keys()):
            if _is_secret_field(section, str(key)) and str(value.get(key, "")).strip():
                value[key] = MASKED_SECRET
    providers = masked.get("custom_providers")
    if isinstance(providers, list):
        for item in providers:
            if isinstance(item, dict) and str(item.get("api_key", "")).strip():
                item["api_key"] = MASKED_SECRET
    return masked

DEFAULT_SETTINGS_TEMPLATE: dict[str, Any] = {
    "api_keys": {
        "deepseek_api_key": "",
        "openrouter_api_key": "",
        "groq_api_key": "",
        "siliconflow_api_key": "",
        "google_api_key": "",
        "dashscope_api_key": "",
        "xiaomi_api_key": "",
        "openai_api_key": "",
        "elevenlabs_api_key": "",
        "ollama_api_key": "",
        "deepgram_api_key": "",
        "gpt_sovits_api_key": "",
        "doubao_api_key": "",
        "doubao_access_token": "",
        "doubao_app_id": "",
        "doubao_websearch_api_key": "",
        "cartesia_api_key": "",
    },
    "api_urls": {
        "Google": "",
        "OpenAI": "",
        "DeepSeek": "",
        "OpenRouter": "",
        "Groq": "",
        "SiliconFlow": "",
        "DashScope": "",
        "MiniMax": "",
        "Xiaomi": "",
        "ElevenLabs": "",
        "Ollama": "",
        "Deepgram": "",
        "GPT-SoVITS": "",
        "Doubao": "",
        "Cartesia": "",
    },
    "realtime_api_urls": {
        "DashScope": "",
        "Doubao": "",
        "Cartesia": "",
    },
    "default_models": {
        "DeepSeek": {"default": "deepseek-v4-flash", "available": ["deepseek-v4-flash", "deepseek-v4-pro"], "enabled": ["deepseek-v4-flash", "deepseek-v4-pro"]},
        "OpenRouter": {"default": "deepseek/deepseek-r1", "available": ["deepseek/deepseek-r1", "google/gemini-2.5-flash", "anthropic/claude-3.5-sonnet"], "enabled": ["deepseek/deepseek-r1", "google/gemini-2.5-flash"]},
        "SiliconFlow": {"default": "deepseek-ai/DeepSeek-V3", "available": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1", "Qwen/Qwen2.5-72B-Instruct"], "enabled": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1"]},
        "Groq": {"default": "llama-3.3-70b-versatile", "available": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "deepseek-r1-distill-llama-70b"], "enabled": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]},
        "DashScope": {"default": "qwen-plus", "available": ["qwen-max", "qwen-plus", "qwen-turbo", "qwen3.5-omni-plus-realtime", "qwen3.5-livetranslate-flash-realtime", "qwen-audio-3.0-realtime-plus"], "enabled": ["qwen-max", "qwen-plus", "qwen3.5-omni-plus-realtime", "qwen3.5-livetranslate-flash-realtime"], "tts_default": "qwen-audio-3.0-tts-flash", "tts_available": ["qwen-audio-3.0-tts-flash", "qwen-audio-3.0-tts-plus", "qwen3-tts-flash-2025-11-27"], "tts_enabled": ["qwen-audio-3.0-tts-flash", "qwen-audio-3.0-tts-plus", "qwen3-tts-flash-2025-11-27"]},
        "Google": {"default": "gemini-3.7-flash", "available": ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.5-transcribe", "gemini-3.1-flash-lite", "gemini-3.1-flash-live-preview", "gemini-3.5-live-translate-preview", "gemini-2.5-flash", "gemini-2.5-pro"], "enabled": ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-3.5-transcribe", "gemini-3.1-flash-live-preview", "gemini-3.5-live-translate-preview"]},
        "MiniMax": {"default": "", "available": [], "enabled": [], "tts_default": "speech-02-turbo", "tts_available": ["speech-02-turbo", "speech-02-hd", "speech-01-turbo", "speech-01-hd"], "tts_enabled": ["speech-02-turbo", "speech-02-hd"]},
        "Xiaomi": {"default": "", "available": [], "enabled": [], "tts_default": "mimo-v2.5-tts", "tts_available": ["mimo-v2.5-tts", "mimo-v2-tts"], "tts_enabled": ["mimo-v2.5-tts"]},
        "OpenAI": {"default": "gpt-4o", "available": ["gpt-4o", "gpt-4o-mini", "gpt-realtime-2", "tts-1", "tts-1-hd"], "enabled": ["gpt-4o", "gpt-4o-mini", "gpt-realtime-2", "tts-1", "tts-1-hd"], "tts_default": "tts-1", "tts_available": ["tts-1", "tts-1-hd"], "tts_enabled": ["tts-1", "tts-1-hd"]},
        "ElevenLabs": {"default": "eleven_multilingual_v2", "available": ["eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_monolingual_v1"], "enabled": ["eleven_multilingual_v2", "eleven_turbo_v2_5"], "tts_default": "eleven_multilingual_v2", "tts_available": ["eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_monolingual_v1"], "tts_enabled": ["eleven_multilingual_v2", "eleven_turbo_v2_5"]},
        "Ollama": {"default": "", "available": [], "enabled": []},
        "Deepgram": {"default": "", "available": [], "enabled": []},
        "GPT-SoVITS": {"default": "", "available": [], "enabled": []},
        "Doubao": {"default": "doubao-realtime", "available": ["doubao-realtime"], "enabled": ["doubao-realtime"]},
        "Cartesia": {"default": "cartesia-realtime", "available": ["cartesia-realtime"], "enabled": ["cartesia-realtime"], "tts_default": "sonic-preview", "tts_available": ["sonic-preview", "sonic-3.5", "sonic-3"], "tts_enabled": ["sonic-preview", "sonic-3.5"]},
        "PersonaPlex": {"default": "personaplex-7b-v1-bnb-4bit", "available": ["personaplex-7b-v1-bnb-4bit"], "enabled": ["personaplex-7b-v1-bnb-4bit"]},
        "GLM4Voice": {"default": "glm-4-voice-9b", "available": ["glm-4-voice-9b"], "enabled": ["glm-4-voice-9b"]},
    },
    "general_settings": {
        "display_language": "English",
        "history_retention": "Keep all history",
        "log_level": "INFO",
    },
    "memory_settings": {
        "enabled": False,
        "api_url": "https://api.evermind.ai",
        "api_key": "",
        "scope_id": "",
        "remember_chat": True,
        "remember_voice_chat": True,
        "remember_recordings": False,
        "remember_podcast": True,
        "remember_tts": True,
        "store_transcript_fulltext": False,
        "temporary_session": False,
    },
    "output_directory": "",
    "tts_settings": {
        "default_voice": "",
        "auto_play_preview": False,
        "output_folder": "",
        "speech_speed": 1.0,
        "speech_pitch": 1.0,
        "provider": "System TTS",
        "chattts_model_dir": "",
        "chattts_hf_endpoint": "",
        "chattts_device": "auto",
    },
    "qwen_tts_settings": {
        "voice_design_voices": [],
        "voice_clone_voices": [],
        "default_vd_model": "qwen3-tts-vd-realtime-2025-12-16",
        "default_vc_model": "qwen3-tts-vc-realtime-2025-11-27",
    },
    "transcription_settings": {
        "public_base_url": "",
        "upload_mode": "static",
        "s3_bucket": "",
        "s3_region": "",
        "s3_endpoint_url": "",
        "s3_access_key_id": "",
        "s3_secret_access_key": "",
        "s3_key_prefix": "transcription",
    },
    "minimax": {
        "api_key": "",
        "api_url": "",
    },
    "xiaomi": {
        "api_key": "",
        "api_url": "",
    },
    "auth_settings": {
        "api_token": "",
        "admin_token": "",
    },
    "ui_settings": {
        "theme": "default",
        "window_size": [1000, 800],
        "remember_window_position": False,
        "always_on_top": False,
        "show_tray_icon": False,
    },
    "shortcuts": {
        "wake_app": "Alt+Shift+S",
    },
    "custom_providers": [],
}

ALLOWED_UPDATE_SECTIONS = {
    "api_keys",
    "api_urls",
    "realtime_api_urls",
    "default_models",
    "general_settings",
    "memory_settings",
    "output_directory",
    "tts_settings",
    "qwen_tts_settings",
    "transcription_settings",
    "minimax",
    "xiaomi",
    "auth_settings",
    "ui_settings",
    "shortcuts",
    "custom_providers",
}


class SettingsService:
    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig()

    @staticmethod
    def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                SettingsService._deep_merge(target[key], value)
            else:
                target[key] = value
        return target

    def _normalize_models(self, value: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for provider, model_data in value.items():
            provider_name = str(provider).strip()
            if not provider_name:
                continue
            if isinstance(model_data, str):
                normalized[provider_name] = model_data.strip()
                continue
            if not isinstance(model_data, dict):
                raise ValueError(f"default_models.{provider_name} must be a string or object.")

            default_model = str(model_data.get("default", "")).strip()
            available_raw = model_data.get("available", [])
            if not isinstance(available_raw, list):
                raise ValueError(f"default_models.{provider_name}.available must be an array.")
            available = [str(item).strip() for item in available_raw if str(item).strip()]

            enabled_raw = model_data.get("enabled", [])
            if not isinstance(enabled_raw, list):
                enabled_raw = []
            enabled = [str(item).strip() for item in enabled_raw if str(item).strip()]

            # Guarantee default model is available and enabled if specified
            if default_model:
                if default_model not in available:
                    available.append(default_model)
                if enabled and default_model not in enabled:
                    enabled.append(default_model)

            tts_default = str(model_data.get("tts_default", "")).strip()
            tts_available_raw = model_data.get("tts_available", [])
            tts_available = [str(item).strip() for item in tts_available_raw if str(item).strip()] if isinstance(tts_available_raw, list) else []
            tts_enabled_raw = model_data.get("tts_enabled", [])
            tts_enabled = [str(item).strip() for item in tts_enabled_raw if str(item).strip()] if isinstance(tts_enabled_raw, list) else []

            if tts_default:
                if tts_default not in tts_available:
                    tts_available.append(tts_default)
                if tts_enabled and tts_default not in tts_enabled:
                    tts_enabled.append(tts_default)

            item_dict: dict[str, Any] = {
                "default": default_model,
                "available": available,
                "enabled": enabled,
            }
            if tts_default or tts_available or tts_enabled:
                item_dict["tts_default"] = tts_default
                item_dict["tts_available"] = tts_available
                item_dict["tts_enabled"] = tts_enabled

            normalized[provider_name] = item_dict
        return normalized

    @staticmethod
    def _normalize_str_dict(value: dict[str, Any]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, item in value.items():
            normalized[str(key)] = str(item).strip()
        return normalized

    @staticmethod
    def _normalize_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _normalize_memory_settings(self, value: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        allowed_keys = DEFAULT_SETTINGS_TEMPLATE["memory_settings"].keys()

        for key, item in value.items():
            canonical_key = MEMORY_SETTINGS_ALIASES.get(str(key), str(key))
            if canonical_key not in allowed_keys:
                continue
            if canonical_key in MEMORY_SETTINGS_BOOL_KEYS:
                normalized[canonical_key] = self._normalize_bool(item)
                continue
            if canonical_key in MEMORY_SETTINGS_STR_KEYS:
                normalized[canonical_key] = str(item).strip()
                continue
            normalized[canonical_key] = copy.deepcopy(item)

        return normalized

    def _normalize_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("settings must be an object.")
        unknown = [key for key in patch.keys() if key not in ALLOWED_UPDATE_SECTIONS]
        if unknown:
            raise ValueError(f"Unsupported settings section: {', '.join(sorted(unknown))}")

        normalized: dict[str, Any] = {}
        for key, value in patch.items():
            if key == "output_directory":
                normalized[key] = str(value).strip()
                continue

            if key in {"api_keys", "api_urls", "realtime_api_urls"}:
                if not isinstance(value, dict):
                    raise ValueError(f"{key} must be an object.")
                normalized[key] = self._normalize_str_dict(value)
                continue

            if key == "default_models":
                if not isinstance(value, dict):
                    raise ValueError("default_models must be an object.")
                normalized[key] = self._normalize_models(value)
                continue

            if key == "memory_settings":
                if not isinstance(value, dict):
                    raise ValueError("memory_settings must be an object.")
                normalized[key] = self._normalize_memory_settings(value)
                continue

            if key == "custom_providers":
                if not isinstance(value, list):
                    raise ValueError("custom_providers must be an array.")
                normalized[key] = [copy.deepcopy(item) for item in value if isinstance(item, dict)]
                continue

            if not isinstance(value, dict):
                raise ValueError(f"{key} must be an object.")
            normalized[key] = copy.deepcopy(value)

        return normalized

    def _build_settings_response(self, data: dict[str, Any]) -> dict[str, Any]:
        merged = copy.deepcopy(DEFAULT_SETTINGS_TEMPLATE)
        self._deep_merge(merged, data)
        memory_settings = merged.get("memory_settings", {})
        if isinstance(memory_settings, dict):
            canonical_memory_settings = copy.deepcopy(DEFAULT_SETTINGS_TEMPLATE["memory_settings"])
            canonical_memory_settings.update(self._normalize_memory_settings(memory_settings))
            merged["memory_settings"] = canonical_memory_settings
        api_urls = merged.get("api_urls", {})
        if isinstance(api_urls, dict):
            for provider, default_url in DEFAULT_BASE_URLS.items():
                if provider not in api_urls:
                    api_urls[provider] = default_url
        
        custom_providers = merged.get("custom_providers", [])
        custom_ids = [str(p.get("id")) for p in custom_providers if isinstance(p, dict) and p.get("id")]

        return {
            "config_path": str(self.config.config_path),
            "providers": list(SETTINGS_PROVIDERS) + custom_ids,
            "settings": _mask_secrets(merged),
        }

    def _resolve_masked_secrets(self, patch: dict[str, Any]) -> None:
        """Substitute MASKED_SECRET placeholders in an incoming patch with the
        currently stored values, so a client that round-trips masked settings
        never overwrites real credentials."""
        current = self.config.get_all()
        for section, incoming in patch.items():
            if not isinstance(incoming, dict):
                continue
            stored_section = current.get(section)
            stored = stored_section if isinstance(stored_section, dict) else {}
            for key in incoming.keys():
                if _is_secret_field(section, str(key)) and incoming[key] == MASKED_SECRET:
                    incoming[key] = str(stored.get(key, "") or "")
        providers = patch.get("custom_providers")
        if isinstance(providers, list):
            stored_providers = current.get("custom_providers")
            stored_by_id = (
                {str(p.get("id")): p for p in stored_providers if isinstance(p, dict)}
                if isinstance(stored_providers, list)
                else {}
            )
            for item in providers:
                if not isinstance(item, dict) or item.get("api_key") != MASKED_SECRET:
                    continue
                existing = stored_by_id.get(str(item.get("id", "")))
                item["api_key"] = str((existing or {}).get("api_key", "") or "")

    def reveal_secret(self, section: str, key: str = "", provider_id: str = "") -> str:
        """Return the real credential hidden behind a MASKED_SECRET placeholder.

        Only fields recognized by ``_is_secret_field`` (or a custom provider
        matched by id) may be revealed; anything else raises ``KeyError`` so
        the endpoint can never be abused as a generic config reader.
        """
        self.config.reload()
        data = self.config.get_all()
        if section == "custom_providers":
            providers = data.get("custom_providers")
            if isinstance(providers, list):
                for item in providers:
                    if isinstance(item, dict) and str(item.get("id", "")) == provider_id:
                        return str(item.get("api_key", "") or "")
            raise KeyError(f"unknown custom provider id: {provider_id!r}")
        if not _is_secret_field(section, key):
            raise KeyError(f"not a secret field: {section}.{key}")
        node = data.get(section)
        if not isinstance(node, dict):
            return ""
        return str(node.get(key, "") or "")

    def get_settings(self) -> dict[str, Any]:
        self.config.reload()
        return self._build_settings_response(self.config.get_all())

    def update_settings(self, patch: dict[str, Any], merge: bool = True) -> dict[str, Any]:
        normalized_patch = self._normalize_patch(patch)
        self._resolve_masked_secrets(normalized_patch)
        updated = self.config.update(normalized_patch, merge=merge)
        return self._build_settings_response(updated)
