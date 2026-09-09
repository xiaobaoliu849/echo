from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from services.config_loader import BackendConfig
from services.elevenlabs_voice_service import ElevenLabsVoiceService


def _service_with_config(tmp_path: Path, *, api_key: str = "test-elevenlabs-key") -> ElevenLabsVoiceService:
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"api_keys": {"elevenlabs_api_key": api_key}}), encoding="utf-8")
    return ElevenLabsVoiceService(config=BackendConfig(config_path=config_file))


def _patch_async_client_transport(transport: httpx.MockTransport):
    original_init = httpx.AsyncClient.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["transport"] = transport
        original_init(self, *args, **kwargs)

    return patch.object(httpx.AsyncClient, "__init__", patched_init)


def test_clone_uploads_multipart_and_returns_voice_id(tmp_path: Path) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("xi-api-key")
        captured["body"] = request.content
        return httpx.Response(200, json={"voice_id": "vc_abc123"})

    service = _service_with_config(tmp_path)
    with _patch_async_client_transport(httpx.MockTransport(handler)):
        result = asyncio.run(
            service.create_voice_clone(
                audio_bytes=b"RIFFdata",
                mime_type="audio/wav",
                preferred_name="demo",
            )
        )

    assert result["voice"] == "vc_abc123"
    assert result["type"] == "voice_clone"
    assert result["preferred_name"] == "demo"
    assert captured["url"].endswith("/voices/add")
    assert captured["auth"] == "test-elevenlabs-key"
    assert b'name="name"' in captured["body"]
    assert b"demo" in captured["body"]


def test_clone_requires_api_key(tmp_path: Path) -> None:
    service = _service_with_config(tmp_path, api_key="")
    with pytest.raises(ValueError, match="Missing ElevenLabs API key"):
        asyncio.run(
            service.create_voice_clone(
                audio_bytes=b"RIFFdata",
                mime_type="audio/wav",
                preferred_name="demo",
            )
        )


def test_clone_requires_preferred_name(tmp_path: Path) -> None:
    service = _service_with_config(tmp_path)
    with pytest.raises(ValueError, match="preferred_name"):
        asyncio.run(
            service.create_voice_clone(
                audio_bytes=b"RIFFdata",
                mime_type="audio/wav",
                preferred_name="  ",
            )
        )


def test_clone_upstream_error_raises_runtime_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": {"status": "too_many_voice_add_requests", "message": "quota"}})

    service = _service_with_config(tmp_path)
    with _patch_async_client_transport(httpx.MockTransport(handler)):
        with pytest.raises(RuntimeError, match="quota"):
            asyncio.run(
                service.create_voice_clone(
                    audio_bytes=b"RIFFdata",
                    mime_type="audio/wav",
                    preferred_name="demo",
                )
            )


def test_list_filters_to_cloned_category(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/voices")
        return httpx.Response(
            200,
            json={
                "voices": [
                    {"voice_id": "vc_clone_1", "name": "My Clone", "category": "cloned", "labels": {"language": "en", "gender": "female"}},
                    {"voice_id": "vc_stock", "name": "Adam", "category": "premade"},
                ]
            },
        )

    service = _service_with_config(tmp_path)
    with _patch_async_client_transport(httpx.MockTransport(handler)):
        result = asyncio.run(service.list_voices())

    assert result["voice_type"] == "voice_clone"
    assert result["count"] == 1
    assert result["voices"][0]["voice"] == "vc_clone_1"
    assert result["voices"][0]["name"] == "My Clone"
    assert result["voices"][0]["language"] == "en"


def test_delete_reports_missing_voice_as_not_deleted(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/voices/vc_missing")
        return httpx.Response(404, json={"detail": {"status": "not_found"}})

    service = _service_with_config(tmp_path)
    with _patch_async_client_transport(httpx.MockTransport(handler)):
        result = asyncio.run(service.delete_voice(voice_name="vc_missing"))

    assert result == {"voice": "vc_missing", "type": "voice_clone", "deleted": False}


def test_delete_success(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    service = _service_with_config(tmp_path)
    with _patch_async_client_transport(httpx.MockTransport(handler)):
        result = asyncio.run(service.delete_voice(voice_name="vc_ok"))

    assert result == {"voice": "vc_ok", "type": "voice_clone", "deleted": True}
