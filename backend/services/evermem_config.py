"""Shared EverMemOS configuration helpers."""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any
from urllib.parse import urlparse

from .evermem_service import EverMemService # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_EVERMEM_URL = os.getenv("EVERMEM_API_URL", "https://api.evermind.ai").strip()


def _url_origin_allowed(url: str, trusted_url: str) -> bool:
    parsed = urlparse(url)
    trusted = urlparse(trusted_url)
    return (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and parsed.netloc.lower() == trusted.netloc.lower()
    )


def _clean_header_value(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _get_header_value(headers: dict[str, Any], *names: str) -> str:
    if not isinstance(headers, dict):
        return ""

    for name in names:
        value = headers.get(name)
        cleaned = _clean_header_value(value)
        if cleaned:
            return cleaned

    normalized = {str(key).lower(): value for key, value in headers.items()}
    for name in names:
        cleaned = _clean_header_value(normalized.get(name.lower()))
        if cleaned:
            return cleaned
    return ""


def _hash_scope(prefix: str, raw: str) -> str:
    # Use explicit intermediate variables to help the IDE linter resolve types
    full_digest: str = hashlib.sha256(str(raw).encode("utf-8")).hexdigest()
    digest: str = full_digest[:24] # type: ignore
    return f"{prefix}_{digest}"


class EverMemConfig:
    def __init__(self) -> None:
        self.enabled: bool = False
        self.url: str = DEFAULT_EVERMEM_URL
        self.key: str | None = None
        self.memory_scope: str = "anonymous"
        self.group_id: str = ""
        self._service: EverMemService | None = None

    def _resolve_scope(self, headers: dict[str, Any]) -> str:
        explicit_scope = _get_header_value(headers, "X-EverMem-Scope", "scope_id", "scopeId")
        if explicit_scope:
            return explicit_scope

        client_id = _get_header_value(headers, "X-Client-ID")
        if client_id:
            return _hash_scope("client", client_id)

        authorization = str(_get_header_value(headers, "Authorization"))
        if authorization.lower().startswith("bearer "):
            # Split and slice in a way that is most likely to be understood by the linter
            token_raw: str = authorization[7:] # type: ignore
            token: str = token_raw.strip()
            if token:
                token_str = str(token)
                return _hash_scope("token", token_str)

        request_id = _get_header_value(headers, "X-Request-ID")
        if request_id:
            return _hash_scope("request", request_id)

        return "anonymous"

    def update_from_headers(self, headers: dict[str, Any]) -> None:
        enabled_header = _get_header_value(headers, "X-EverMem-Enabled", "enabled").lower()
        header_url = _get_header_value(headers, "X-EverMem-Url", "api_url", "url")
        header_key = _get_header_value(headers, "X-EverMem-Key", "api_key", "key")
        self.group_id = _get_header_value(headers, "X-EverMem-Group-ID", "group_id", "groupId")
        env_key = os.getenv("EVERMEM_API_KEY", "").strip()

        # Only clean http(s) URLs are accepted; anything else falls back to the
        # default endpoint instead of being passed through verbatim.
        parsed_url = urlparse(header_url) if header_url else None
        if parsed_url is not None and (
            parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc
        ):
            logger.warning(
                "Rejected invalid EverMem URL from request headers: %.200s",
                header_url,
            )
            header_url = ""

        self.enabled = enabled_header == "true"
        self.url = header_url or DEFAULT_EVERMEM_URL

        if header_key:
            # A client-supplied key paired with a client-chosen URL is the
            # documented bring-your-own-endpoint flow.
            self.key = header_key
        elif env_key and _url_origin_allowed(self.url, DEFAULT_EVERMEM_URL):
            # The server-side credential is only ever attached when the target
            # is the trusted default host — never to an arbitrary client URL.
            self.key = env_key
        else:
            self.key = None
        self.memory_scope = self._resolve_scope(headers)

        if self.enabled and self.key:
            self._service = EverMemService(api_url=self.url, api_key=self.key)
        else:
            self._service = None

    def get_service(self) -> EverMemService | None:
        return self._service
