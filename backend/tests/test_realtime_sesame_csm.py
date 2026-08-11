"""Unit test suite for the Sesame CSM-1B local realtime provider mixin."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket

from services.realtime_constants import (
    DEFAULT_SESAME_CSM_REALTIME_MODEL,
    DEFAULT_SESAME_CSM_SERVER_URL,
)
from services.realtime_sesame_csm_provider import RealtimeSesameCsmMixin


class DummySesameCsmService(RealtimeSesameCsmMixin):
    def __init__(self):
        self.config = MagicMock()
        self.config.get_provider_settings.return_value = {
            "model": DEFAULT_SESAME_CSM_REALTIME_MODEL,
            "realtime_base_url": DEFAULT_SESAME_CSM_SERVER_URL,
        }
        self._send_event = AsyncMock()
        self._deliver_assistant_output = AsyncMock()
        self._finalize_realtime_turn = AsyncMock()
        self._create_voice_session_recorder = AsyncMock(return_value=None)
        self._run_duplex_tasks = AsyncMock()


def test_resolve_sesame_csm_url():
    service = DummySesameCsmService()
    url = service._resolve_sesame_csm_url({"realtime_base_url": "ws://127.0.0.1:8997"})
    assert url == "ws://127.0.0.1:8997"

    url_http = service._resolve_sesame_csm_url({"realtime_base_url": "127.0.0.1:8997"})
    assert url_http == "ws://127.0.0.1:8997"


def test_resolve_sesame_csm_settings_defaults():
    service = DummySesameCsmService()
    settings = service._resolve_sesame_csm_settings(None)
    assert settings["model"] == DEFAULT_SESAME_CSM_REALTIME_MODEL
    assert settings["realtime_base_url"] == DEFAULT_SESAME_CSM_SERVER_URL


@pytest.mark.asyncio
async def test_stream_sesame_csm_session_connection_failure():
    service = DummySesameCsmService()
    mock_ws = AsyncMock(spec=WebSocket)

    with patch("aiohttp.ClientSession.ws_connect", side_effect=OSError("Connection refused")):
        await service.stream_sesame_csm_session(mock_ws)

    service._send_event.assert_called_with(
        mock_ws,
        "error",
        message="无法连接本地 Sesame CSM-1B 服务（ws://127.0.0.1:8997/api/chat）：Connection refused。请确认已双击运行 run_sesame_csm_server.bat，且该服务支持 WebSocket 语音对语音协议。",
    )
