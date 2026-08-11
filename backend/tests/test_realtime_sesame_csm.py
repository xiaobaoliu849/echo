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
        self.settings_service = MagicMock()
        self.settings_service.get_realtime_settings.return_value = {
            "model": DEFAULT_SESAME_CSM_REALTIME_MODEL,
            "realtime_base_url": DEFAULT_SESAME_CSM_SERVER_URL,
        }
        self.memory_service = MagicMock()
        self._send_event = AsyncMock()
        self._deliver_assistant_output = AsyncMock()
        self._finalize_realtime_turn = AsyncMock()
        self._start_session_recorder = AsyncMock(return_value=None)
        self._stop_session_recorder = AsyncMock()
        self._run_duplex_tasks = AsyncMock()


def test_resolve_sesame_csm_url():
    service = DummySesameCsmService()
    url = service._resolve_sesame_csm_url({"realtime_base_url": "ws://127.0.0.1:8997"})
    assert url == "ws://127.0.0.1:8997"

    url_http = service._resolve_sesame_csm_url({"realtime_base_url": "127.0.0.1:8997"})
    assert url_http == "ws://127.0.0.1:8997"


@pytest.mark.asyncio
async def test_stream_sesame_csm_session_connection_failure():
    service = DummySesameCsmService()
    mock_ws = AsyncMock(spec=WebSocket)

    with patch("aiohttp.ClientSession.ws_connect", side_effect=OSError("Connection refused")):
        await service.stream_sesame_csm_session(mock_ws)

    service._send_event.assert_called_with(
        mock_ws,
        "error",
        message="无法连接本地 Sesame CSM-1B 服务 (ws://127.0.0.1:8997/api/chat)。请检查是否已双击运行 run_sesame_csm_server.bat 启动该服务。",
    )
