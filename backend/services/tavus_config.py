"""Tavus request configuration.

Resolves the credential and default PAL per request. The client may bring
its own key via X-Tavus-* headers (stored locally in the frontend); the
Settings config.json (api_keys.tavus_api_key / tavus_settings.default_pal_id)
and server-side environment (TAVUS_API_KEY / TAVUS_PAL_ID) act as fallbacks
so desktop deployments can pin a shared account.
"""
from __future__ import annotations

import os
from typing import Any

from .tavus_service import DEFAULT_TAVUS_API_URL, TavusService


def _clean_header_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


class TavusConfig:
    def __init__(self) -> None:
        self.api_key: str | None = None
        self.pal_id: str | None = None
        self.api_url: str = os.getenv("TAVUS_API_URL", "").strip() or DEFAULT_TAVUS_API_URL
        self._service: TavusService | None = None

    def update_from_headers(self, headers: dict[str, Any]) -> None:
        normalized = {str(key).lower(): value for key, value in headers.items()}
        header_key = _clean_header_value(normalized.get("x-tavus-api-key"))
        header_pal = _clean_header_value(normalized.get("x-tavus-pal-id"))

        # Config.json fallback (managed via Settings page).
        config_key = ""
        config_pal = ""
        try:
            from .config_loader import BackendConfig
            cfg = BackendConfig()
            api_keys = cfg.get("api_keys") or {}
            config_key = str(api_keys.get("tavus_api_key", "")).strip()
            tavus_settings = cfg.get("tavus_settings") or {}
            config_pal = str(tavus_settings.get("default_pal_id", "")).strip()
        except Exception:
            pass

        env_key = os.getenv("TAVUS_API_KEY", "").strip()
        env_pal = os.getenv("TAVUS_PAL_ID", "").strip()

        self.api_key = header_key or config_key or env_key or None
        self.pal_id = header_pal or config_pal or env_pal or None

        if self.api_key:
            self._service = TavusService(api_key=self.api_key, api_url=self.api_url)
        else:
            self._service = None

    def get_service(self) -> TavusService | None:
        return self._service
