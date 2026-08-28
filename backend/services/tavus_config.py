"""Tavus request configuration.

Resolves the credential and default PAL per request. The client may bring
its own key via X-Tavus-* headers (stored locally in the frontend); the
server-side environment (TAVUS_API_KEY / TAVUS_PAL_ID) acts as a fallback
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
        # Starlette lowercases header names when they are materialized into a
        # plain dict, so look up case-insensitively.
        normalized = {str(key).lower(): value for key, value in headers.items()}
        header_key = _clean_header_value(normalized.get("x-tavus-api-key"))
        env_key = os.getenv("TAVUS_API_KEY", "").strip()
        header_pal = _clean_header_value(normalized.get("x-tavus-pal-id"))
        env_pal = os.getenv("TAVUS_PAL_ID", "").strip()

        self.api_key = header_key or env_key or None
        self.pal_id = header_pal or env_pal or None

        if self.api_key:
            self._service = TavusService(api_key=self.api_key, api_url=self.api_url)
        else:
            self._service = None

    def get_service(self) -> TavusService | None:
        return self._service
