import logging

from services.logging_setup import _RedactWebSocketToken, _install_access_log_redaction


def test_uvicorn_access_log_redacts_websocket_token() -> None:
    _install_access_log_redaction()
    _install_access_log_redaction()
    access_logger = logging.getLogger("uvicorn.access")
    assert sum(isinstance(item, _RedactWebSocketToken) for item in access_logger.filters) == 1

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "WebSocket %s" [accepted]',
        ("127.0.0.1:1234", "/api/voice-chat/ws?provider=DashScope&token=secret-value&model=qwen-audio"),
        None,
    )
    for item in access_logger.filters:
        item.filter(record)
    formatted = record.getMessage()
    assert "secret-value" not in formatted
    assert "token=<redacted>" in formatted
    assert "provider=DashScope" in formatted
