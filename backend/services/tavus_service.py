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
        """Return all PAL pages, accepting legacy response envelopes too."""
        return await self._list_items("/v2/pals", ("pals", "personas"))

    async def create_conversation(
        self,
        *,
        pal_id: str,
        conversation_name: str | None = None,
        face_id: str | None = None,
        properties: dict[str, Any] | None = None,
        test_mode: bool = False,
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
        if test_mode:
            payload["test_mode"] = True

        data = await self._request_json("POST", "/v2/conversations", json_payload=payload)
        if not isinstance(data, dict):
            raise TavusError("TAVUS_RESPONSE_INVALID", "Tavus conversation response is not an object.")
        conversation_url = data.get("conversation_url")
        conversation_id = data.get("conversation_id")
        if not isinstance(conversation_url, str) or not conversation_url.strip():
            raise TavusError(
                "TAVUS_RESPONSE_INVALID",
                "Tavus conversation response did not include a conversation_url.",
            )
        if not isinstance(conversation_id, str) or not conversation_id.strip():
            raise TavusError(
                "TAVUS_RESPONSE_INVALID",
                "Tavus conversation response did not include a conversation_id.",
            )
        return data

    async def list_faces(self) -> list[dict[str, Any]]:
        """Return the account's faces (Phoenix-trained video personas, e.g. phoenix-4.5)."""
        return await self._list_items("/v2/faces", ("faces", "replicas"))

    async def _list_items(self, path: str, aliases: tuple[str, ...]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page = 1
        received = 0
        while True:
            data = await self._request_json("GET", f"{path}?limit=100&page={page}")
            batch: Any = data
            total = None
            if isinstance(data, dict):
                batch = next((data[key] for key in ("data", *aliases) if key in data), None)
                total = data.get("total_count")
            if not isinstance(batch, list):
                raise TavusError("TAVUS_RESPONSE_INVALID", "Tavus list response is not a list.")
            items.extend(item for item in batch if isinstance(item, dict))
            received += len(batch)
            if not batch or not isinstance(total, int) or received >= total:
                return items
            page += 1

    async def end_conversation(self, conversation_id: str) -> None:
        """End a live conversation. Ending an already-ended call is a no-op."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.request(
                    method="POST",
                    url=f"{self.api_url}/v2/conversations/{conversation_id}/end",
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
