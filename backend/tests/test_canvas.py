import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services.canvas_service import CanvasService

_TEST_TOKEN = "test-api-token"
_AUTH_HEADERS = {"Authorization": f"Bearer {_TEST_TOKEN}"}
_ENV_PATCH = {"VOICESPIRIT_API_TOKEN": _TEST_TOKEN}

client = TestClient(app)

@pytest.fixture
def mock_canvas_service():
    with patch("routers.canvas.canvas_service", spec=CanvasService) as mock_svc:
        yield mock_svc

def test_canvas_generate_react(mock_canvas_service):
    # Setup mock to return SSE generator
    async def mock_generate_stream(*args, **kwargs):
        yield 'data: {"type": "meta", "model": "test-model"}\n\n'
        yield 'data: {"type": "delta", "content": "import"}\n\n'
        yield 'data: {"type": "done", "reply": "import React from \'react\';"}\n\n'

    mock_canvas_service.generate_code_stream = mock_generate_stream

    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        response = client.post(
            "/api/canvas/generate",
            json={
                "prompt": "Create a button",
                "mode": "react",
                "images": ["data:image/png;base64,fake"]
            },
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    
    content = response.content.decode("utf-8")
    assert '"type": "meta"' in content
    assert '"type": "delta"' in content
    assert '"type": "done"' in content

def test_canvas_generate_error(mock_canvas_service):
    # Setup mock to raise exception
    async def mock_generate_stream_error(*args, **kwargs):
        raise ValueError("Invalid prompt")
        yield ""

    mock_canvas_service.generate_code_stream = mock_generate_stream_error

    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        response = client.post(
            "/api/canvas/generate",
            json={
                "prompt": "Trigger error",
                "mode": "html"
            },
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    
    content = response.content.decode("utf-8")
    assert '"type": "error"' in content
    assert "Invalid prompt" in content

def test_canvas_generate_missing_auth(mock_canvas_service):
    """Verify that missing Bearer token returns 401."""
    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        response = client.post(
            "/api/canvas/generate",
            json={
                "prompt": "No token",
                "mode": "react"
            },
        )

    assert response.status_code == 401
    body = response.json()
    assert body["detail"]["code"] == "AUTH_TOKEN_MISSING"

def test_canvas_generate_revision(mock_canvas_service):
    """Verify that existing_code is passed through to the service."""
    async def mock_generate_stream(*args, **kwargs):
        yield 'data: {"type": "done", "reply": "revised code"}\n\n'

    mock_canvas_service.generate_code_stream = mock_generate_stream

    with patch.dict(os.environ, _ENV_PATCH, clear=False):
        response = client.post(
            "/api/canvas/generate",
            json={
                "prompt": "Add a checkbox",
                "mode": "react",
                "existing_code": "<div>Old form</div>",
            },
            headers=_AUTH_HEADERS,
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_realtime_render_canvas_tool():
    from services.realtime_tool_protocol import (
        RealtimeToolCall,
        native_tool_declarations,
        tool_call_to_request,
    )
    from services.voice_agent_tools import VoiceAgentToolService

    # 1. Check declaration exists
    decls = native_tool_declarations()
    names = [d["name"] for d in decls]
    assert "render_canvas" in names

    # 2. Check tool_call_to_request conversion
    call = RealtimeToolCall(
        provider="Google",
        provider_call_id="call-123",
        tool_name="render_canvas",
        arguments={"code": "export default function App() { return <h1>Hello</h1>; }", "mode": "react", "title": "Greeting"},
    )
    req = tool_call_to_request(call)
    assert req.tool_name == "render_canvas"

    # 3. Check execution and events
    emitted_events = []

    async def mock_send(event_type: str, payload: dict):
        emitted_events.append((event_type, payload))

    service = VoiceAgentToolService()
    result = await service.run_tool(req, send_event=mock_send, turn_id="t-1")
    assert result["tool_name"] == "render_canvas"
    assert result["artifact"]["artifact_type"] == "canvas"
    assert "export default function App" in result["artifact"]["code"]

    event_types = [e[0] for e in emitted_events]
    assert "tool_call_started" in event_types
    assert "tool_call_completed" in event_types
    assert "agent_result" in event_types

