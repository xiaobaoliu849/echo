"""Unit test suite for the GLM-4-Voice local realtime provider mixin."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import WebSocket

from services.realtime_constants import (
    DEFAULT_GLM4VOICE_REALTIME_MODEL,
    DEFAULT_GLM4VOICE_SERVER_URL,
)
from services.realtime_glm4voice_provider import RealtimeGlm4VoiceMixin


class DummyGlm4VoiceService(RealtimeGlm4VoiceMixin):
    def __init__(self):
        self.settings_service = MagicMock()
        self.settings_service.get_realtime_settings.return_value = {
            "model": DEFAULT_GLM4VOICE_REALTIME_MODEL,
            "realtime_base_url": DEFAULT_GLM4VOICE_SERVER_URL,
        }
        self.memory_service = MagicMock()
        self._send_event = AsyncMock()
        self._deliver_assistant_output = AsyncMock()
        self._finalize_realtime_turn = AsyncMock()
        self._start_session_recorder = AsyncMock(return_value=None)
        self._stop_session_recorder = AsyncMock()
        self._run_duplex_tasks = AsyncMock()


def test_resolve_glm4voice_url():
    service = DummyGlm4VoiceService()
    url = service._resolve_glm4voice_url({"realtime_base_url": "ws://127.0.0.1:8999"})
    assert url == "ws://127.0.0.1:8999"

    url_http = service._resolve_glm4voice_url({"realtime_base_url": "127.0.0.1:8999"})
    assert url_http == "ws://127.0.0.1:8999"


@pytest.mark.asyncio
async def test_stream_glm4voice_session_connection_failure():
    service = DummyGlm4VoiceService()
    mock_ws = AsyncMock(spec=WebSocket)

    with patch("aiohttp.ClientSession.ws_connect", side_effect=OSError("Connection refused")):
        await service.stream_glm4voice_session(mock_ws)

    service._send_event.assert_called_with(
        mock_ws,
        "error",
        message="无法连接本地 GLM-4-Voice 服务 (ws://127.0.0.1:8999/api/chat)。请检查是否已双击运行 run_glm4voice_server.bat 启动该服务。",
    )
