from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ClosingConnection(sqlite3.Connection):
    """SQLite connection subclass that automatically closes upon context manager exit."""

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def get_db_connection(
    db_path: Path | str,
    *,
    busy_timeout_ms: int = 5000,
    wal_mode: bool = True,
) -> sqlite3.Connection:
    """Create and configure an SQLite connection with standardized concurrency pragmas.

    - Sets row_factory to sqlite3.Row for dictionary-like column access.
    - Applies PRAGMA busy_timeout=5000 to absorb concurrent read/write lock contention.
    - Sets PRAGMA journal_mode=WAL so readers do not block writers and vice-versa.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        str(path),
        check_same_thread=False,
        factory=ClosingConnection,
    )
    conn.row_factory = sqlite3.Row

    # busy_timeout first: switching journal mode needs exclusive access,
    # and the timeout absorbs brief lock overlaps between repositories
    # sharing this database file instead of raising "database is locked".
    conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")

    if wal_mode:
        # WAL lets UI reads proceed while writers operate.
        # Fall back gracefully if the underlying filesystem lacks shared-memory support.
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            logger.debug("WAL journal mode unavailable for %s", path)

    return conn
