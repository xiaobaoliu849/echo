"""
Tavus PAL Service
Thin async client for the Tavus Developer API (https://tavusapi.com).

A "PAL" is a Tavus real-time video persona. Creating a conversation pairs
the PAL with a Daily-powered WebRTC room and returns a conversation_url the
browser joins with daily-js. The API key must never reach the frontend
bundle; the frontend sends it per-request via X-Tavus-* headers and the
backend attaches it here.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx  # type: ignore

logger = logging.getLogger(__name__)

DEFAULT_TAVUS_API_URL = "https://tavusapi.com"


class TavusError(Exception):
    def __init__(self, code: str, message: str, *, upstream_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.upstream_status = upstream_status


class TavusService:
    def __init__(self, api_key: str, api_url: str = DEFAULT_TAVUS_API_URL) -> None:
        self.api_key = api_key
        self.api_url = (api_url or DEFAULT_TAVUS_API_URL).rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def list_pals(self) -> list[dict[str, Any]]:
        """Return the account's PALs (new API), falling back to legacy personas."""
        data = await self._request_json("GET", "/v2/pals")
        items: Any = data
        if isinstance(data, dict):
            items = data.get("pals", data.get("personas", []))
        if not isinstance(items, list):
            raise TavusError("TAVUS_RESPONSE_INVALID", "Tavus PAL list response is not a list.")
        return [item for item in items if isinstance(item, dict)]

    async def create_conversation(
        self,
        *,
        pal_id: str,
        conversation_name: str | None = None,
        face_id: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a real-time conversation and return its id and join URL."""
        payload: dict[str, Any] = {"pal_id": pal_id}
        if conversation_name:
            payload["conversation_name"] = conversation_name
        if face_id:
            # Only needed when the PAL has no default face; overrides it otherwise.
            payload["face_id"] = face_id
        if properties:
            payload["properties"] = properties

        data = await self._request_json("POST", "/v2/conversations", json_payload=payload)
        if not isinstance(data, dict):
            raise TavusError("TAVUS_RESPONSE_INVALID", "Tavus conversation response is not an object.")
        conversation_url = str(data.get("conversation_url", "")).strip()
        if not conversation_url:
            raise TavusError(
                "TAVUS_RESPONSE_INVALID",
                "Tavus conversation response did not include a conversation_url.",
            )
        return data

    async def end_conversation(self, conversation_id: str) -> None:
        """End a live conversation. Ending an already-ended call is a no-op."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(
                    method="DELETE",
                    url=f"{self.api_url}/v2/conversations/{conversation_id}",
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            raise TavusError(
                "TAVUS_UPSTREAM_UNREACHABLE",
                f"Could not reach the Tavus API: {exc}",
            ) from exc
        if resp.status_code == 404:
            return
        if resp.status_code >= 400:
            raise TavusError(
                "TAVUS_UPSTREAM_ERROR",
                f"Tavus rejected ending conversation {conversation_id}: {resp.text[:300]}",
                upstream_status=resp.status_code,
            )

    async def _request_json(
        self,
        method: str,
        path: str,
        json_payload: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(
                    method=method,
                    url=f"{self.api_url}{path}",
                    headers=self._headers(),
                    json=json_payload,
                )
        except httpx.HTTPError as exc:
            raise TavusError(
                "TAVUS_UPSTREAM_UNREACHABLE",
                f"Could not reach the Tavus API: {exc}",
            ) from exc
        if resp.status_code >= 400:
            raise TavusError(
                "TAVUS_UPSTREAM_ERROR",
                f"Tavus API returned {resp.status_code}: {resp.text[:300]}",
                upstream_status=resp.status_code,
            )
        try:
            return resp.json()
        except ValueError as exc:
            raise TavusError(
                "TAVUS_RESPONSE_INVALID",
                "Tavus API returned a non-JSON response.",
                upstream_status=resp.status_code,
            ) from exc
