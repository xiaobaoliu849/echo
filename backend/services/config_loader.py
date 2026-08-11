from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_data_dir() -> Path:
    """Return the application data directory for VoiceSpirit."""
    explicit_data_dir = os.environ.get("VOICESPIRIT_DATA_DIR", "").strip()
    if explicit_data_dir:
        data_dir = Path(explicit_data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    app_name = "VoiceSpirit"
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(Path.cwd())))
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    data_dir = base / app_name
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_data_file_path(filename: str) -> Path:
    target = get_data_dir() / filename
    if not target.exists():
        legacy_path = PROJECT_ROOT / filename
        if legacy_path.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_path, target)
    return target


PROVIDER_KEY_MAP = {
    "DeepSeek": "deepseek_api_key",
    "OpenRouter": "openrouter_api_key",
    "SiliconFlow": "siliconflow_api_key",
    "Groq": "groq_api_key",
    "DashScope": "dashscope_api_key",
    "Google": "google_api_key",
    "Xiaomi": "xiaomi_api_key",
    "OpenAI": "openai_api_key",
    "ElevenLabs": "elevenlabs_api_key",
    "Ollama": "ollama_api_key",
    "Deepgram": "deepgram_api_key",
    "AssemblyAI": "assemblyai_api_key",
    "GPT-SoVITS": "gpt_sovits_api_key",
    "Doubao": "doubao_api_key",
    # Local speech-to-speech servers — unauthenticated, but need entries so that
    # get_provider_settings resolves base URLs and registers them in provider lists.
    "PersonaPlex": "personaplex_api_key",
    "GLM4Voice": "glm4voice_api_key",
}

GOOGLE_INTERACTIONS_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

DEFAULT_BASE_URLS = {
    "DeepSeek": "https://api.deepseek.com/v1",
    "OpenRouter": "https://openrouter.ai/api/v1",
    "SiliconFlow": "https://api.siliconflow.cn/v1",
    "Groq": "https://api.groq.com/openai/v1",
    "DashScope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "Google": GOOGLE_INTERACTIONS_BASE_URL,
    "Xiaomi": "https://token-plan-sgp.xiaomimimo.com/v1",
    "OpenAI": "https://api.openai.com/v1",
    "ElevenLabs": "https://api.elevenlabs.io/v1",
    "Ollama": "http://localhost:11434/v1",
    "Deepgram": "https://api.deepgram.com/v1",
    "AssemblyAI": "https://api.assemblyai.com",
    "GPT-SoVITS": "http://127.0.0.1:9880",
    "Doubao": "https://openspeech.bytedance.com/api/v3/realtime/dialogue",
    # PersonaPlex and GLM4Voice use local WebSocket URLs
    "PersonaPlex": "",
    "GLM4Voice": "",
}


class BackendConfig:
    def __init__(self, config_path: Path | None = None):
        self.config_path = config_path or self._default_config_path()
        self._config: dict[str, Any] = {}
        self._mtime: float | None = None
        self.reload()

    @staticmethod
    def _default_config_path() -> Path:
        return get_data_file_path("config.json")

    def reload(self, force: bool = False) -> None:
        # 基于 mtime 增量刷新：文件没变就直接用内存缓存，避免每个请求都全量读盘 + deepcopy。
        # 外部手动修改 config.json 时 mtime 会变，仍然能正确重新加载。
        if not self.config_path.exists():
            self._config = {}
            self._mtime = None
            return
        try:
            mtime = self.config_path.stat().st_mtime
        except OSError:
            mtime = None
        if not force and mtime is not None and mtime == self._mtime and self._config:
            return
        try:
            self._config = json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            self._config = {}
        self._mtime = mtime

    def get_all(self) -> dict[str, Any]:
        return copy.deepcopy(self._config)

    def get_setting(self, key: str, default: Any = "") -> Any:
        cfg = self.get_all()
        if key in cfg:
            return cfg[key]
        api_keys = cfg.get("api_keys", {})
        if isinstance(api_keys, dict) and key in api_keys:
            return api_keys[key]
        return default

    @staticmethod
    def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
        for key, value in source.items():
            if (
                key in target
                and isinstance(target[key], dict)
                and isinstance(value, dict)
            ):
                BackendConfig._deep_merge(target[key], value)
            else:
                target[key] = value
        return target

    def save_all(self, data: dict[str, Any]) -> dict[str, Any]:
        self._config = copy.deepcopy(data)
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps(self._config, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        try:
            self._mtime = self.config_path.stat().st_mtime
        except OSError:
            self._mtime = None
        return self.get_all()

    def update(self, patch: dict[str, Any], merge: bool = True) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError("settings patch must be a JSON object.")
        current = self.get_all()
        if merge:
            self._deep_merge(current, patch)
        else:
            current = copy.deepcopy(patch)
        return self.save_all(current)

    def _extract_default_model(self, provider: str) -> str:
        models = self._config.get("default_models", {})
        value = models.get(provider)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            default_model = value.get("default")
            if isinstance(default_model, str):
                return default_model
        return ""

    def get_provider_settings(self, provider: str, model: str | None = None) -> dict[str, str]:
        self.reload()
        
        # Check custom providers first
        custom_providers = self._config.get("custom_providers", [])
        custom_prov = next((p for p in custom_providers if isinstance(p, dict) and p.get("id") == provider), None)
        
        if custom_prov:
            api_key = str(custom_prov.get("api_key", "")).strip()
            base_url = str(custom_prov.get("base_url", "")).strip()
            base_url = base_url.rstrip("/")
            
            selected_model = (model or "").strip() or self._extract_default_model(provider)
            if not selected_model:
                selected_model = str(custom_prov.get("default_model", "")).strip()
                
            import json
            custom_headers = custom_prov.get("custom_headers") or {}
            custom_headers_str = json.dumps(custom_headers)
            use_max_tokens = "True" if custom_prov.get("use_max_completion_tokens") else "False"
            
            return {
                "provider": provider,
                "api_key": api_key,
                "base_url": base_url,
                "model": selected_model,
                "custom_headers": custom_headers_str,
                "use_max_completion_tokens": use_max_tokens,
            }

        api_keys = self._config.get("api_keys", {})
        api_urls = self._config.get("api_urls", {})
        realtime_api_urls = self._config.get("realtime_api_urls", {})

        key_field = PROVIDER_KEY_MAP.get(provider)
        api_key = str(api_keys.get(key_field, "")).strip() if key_field else ""

        base_url = str(api_urls.get(provider, "")).strip()
        if not base_url:
            base_url = DEFAULT_BASE_URLS.get(provider, "").strip()
        base_url = base_url.rstrip("/")

        selected_model = (model or "").strip() or self._extract_default_model(provider)

        return {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "realtime_base_url": str(realtime_api_urls.get(provider, "")).strip().rstrip("/"),
            "model": selected_model,
        }
