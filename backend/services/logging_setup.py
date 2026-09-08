"""Rotating-file logging for the backend.

Until this module existed the app had no ``FileHandler`` anywhere: every log
line went to the uvicorn console and was lost when the window closed, which
made post-hoc diagnosis of realtime-voice failures impossible. Log file lives
next to ``config.json`` in the app data dir so it is easy to find.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from services.config_loader import get_data_dir

_HANDLER_TAG = "echo_backend_file_handler"

LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "backend.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3


def log_file_path() -> Path:
    return get_data_dir() / LOG_DIR_NAME / LOG_FILE_NAME


def setup_file_logging() -> Path | None:
    """Attach a rotating file handler to the root logger, once.

    Returns the log path, or ``None`` if file logging is disabled or the file
    cannot be opened (read-only install dir, permissions, ...). Failing to open
    a log file must never prevent the app from starting.
    """
    if os.environ.get("ECHO_DISABLE_FILE_LOG", "").strip().lower() in {"1", "true", "yes"}:
        return None

    root = logging.getLogger()
    for existing in root.handlers:
        if getattr(existing, "_echo_tag", "") == _HANDLER_TAG:
            return getattr(existing, "baseFilename", None) and Path(existing.baseFilename)

    try:
        path = log_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None

    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    level_name = os.environ.get("ECHO_LOG_LEVEL", "INFO").strip().upper()
    handler.setLevel(getattr(logging, level_name, logging.INFO))
    handler._echo_tag = _HANDLER_TAG  # type: ignore[attr-defined]

    root.addHandler(handler)
    # The root logger defaults to WARNING, which would swallow our INFO
    # diagnostics before they ever reach the handler.
    if root.level == logging.NOTSET or root.level > handler.level:
        root.setLevel(handler.level)
    return path
