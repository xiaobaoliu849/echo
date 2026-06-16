from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


class AudioAgentRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or self._default_db_path()
        self._init_db()

    @staticmethod
    def _default_db_path() -> Path:
        from .config_loader import get_data_dir
        return get_data_dir() / "voice_spirit.db"

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            factory=ClosingConnection,
        )
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _decode_json(value: Any, *, fallback: Any) -> Any:
        if isinstance(value, str) and value.strip():
            try:
                return json.loads(value)
            except Exception:
                return fallback
        return fallback

    @staticmethod
    def _row_to_run(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "podcast_id": row["podcast_id"],
            "topic": str(row["topic"]),
            "language": str(row["language"]),
            "status": str(row["status"]),
            "current_step": str(row["current_step"]),
            "provider": str(row["provider"]),
            "model": str(row["model"] or ""),
            "use_memory": bool(row["use_memory"]),
            "input_payload": AudioAgentRepository._decode_json(row["input_payload"], fallback={}),
            "result_payload": AudioAgentRepository._decode_json(row["result_payload"], fallback={}),
            "error_code": str(row["error_code"] or ""),
            "error_message": str(row["error_message"] or ""),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "completed_at": str(row["completed_at"] or ""),
        }

    @staticmethod
    def _row_to_step(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "run_id": int(row["run_id"]),
            "step_name": str(row["step_name"]),
            "status": str(row["status"]),
            "attempt_index": int(row["attempt_index"]),
            "started_at": str(row["started_at"] or ""),
            "finished_at": str(row["finished_at"] or ""),
            "meta": AudioAgentRepository._decode_json(row["meta_json"], fallback={}),
            "error_code": str(row["error_code"] or ""),
            "error_message": str(row["error_message"] or ""),
        }

    @staticmethod
    def _row_to_source(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "run_id": int(row["run_id"]),
            "source_type": str(row["source_type"]),
            "title": str(row["title"] or ""),
            "uri": str(row["uri"] or ""),
            "snippet": str(row["snippet"] or ""),
            "content": str(row["content"] or ""),
            "score": float(row["score"] or 0.0),
            "meta": AudioAgentRepository._decode_json(row["meta_json"], fallback={}),
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "run_id": int(row["run_id"]),
            "event_type": str(row["event_type"]),
            "payload": AudioAgentRepository._decode_json(row["payload_json"], fallback={}),
            "created_at": str(row["created_at"]),
        }

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audio_agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    podcast_id INTEGER,
                    topic TEXT NOT NULL,
                    language TEXT NOT NULL DEFAULT 'zh',
                    status TEXT NOT NULL,
                    current_step TEXT NOT NULL DEFAULT 'prepare',
                    provider TEXT NOT NULL DEFAULT 'DashScope',
                    model TEXT,
                    use_memory INTEGER NOT NULL DEFAULT 1,
                    input_payload TEXT NOT NULL,
                    result_payload TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audio_agent_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    step_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_index INTEGER NOT NULL DEFAULT 1,
                    started_at TIMESTAMP,
                    finished_at TIMESTAMP,
                    meta_json TEXT,
                    error_code TEXT,
                    error_message TEXT,
                    FOREIGN KEY(run_id) REFERENCES audio_agent_runs(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audio_agent_sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    source_type TEXT NOT NULL,
                    title TEXT,
                    uri TEXT,
                    snippet TEXT,
                    content TEXT,
                    score REAL,
                    meta_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES audio_agent_runs(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audio_agent_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(run_id) REFERENCES audio_agent_runs(id)
                )
                """
            )
            conn.commit()

    def create_run(
        self,
        *,
        topic: str,
        language: str,
        status: str,
        current_step: str,
        provider: str,
        model: str,
        use_memory: bool,
        input_payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audio_agent_runs (
                    topic,
                    language,
                    status,
                    current_step,
                    provider,
                    model,
                    use_memory,
                    input_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    topic,
                    language,
                    status,
                    current_step,
                    provider,
                    model or None,
                    1 if use_memory else 0,
                    json.dumps(input_payload, ensure_ascii=False),
                ),
            )
            conn.commit()
            run_id = int(cursor.lastrowid)
        run = self.get_run(run_id)
        if run is None:
            raise RuntimeError("Failed to load created audio agent run.")
        return run

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    id,
                    podcast_id,
                    topic,
                    language,
                    status,
                    current_step,
                    provider,
                    model,
                    use_memory,
                    input_payload,
                    result_payload,
                    error_code,
                    error_message,
                    created_at,
                    updated_at,
                    completed_at
                FROM audio_agent_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()
        return self._row_to_run(row)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    podcast_id,
                    topic,
                    language,
                    status,
                    current_step,
                    provider,
                    model,
                    use_memory,
                    input_payload,
                    result_payload,
                    error_code,
                    error_message,
                    created_at,
                    updated_at,
                    completed_at
                FROM audio_agent_runs
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [item for item in (self._row_to_run(row) for row in rows) if item is not None]

    def add_step(
        self,
        *,
        run_id: int,
        step_name: str,
        status: str,
        attempt_index: int = 1,
        started_at: str | None = None,
        finished_at: str | None = None,
        meta: dict[str, Any] | None = None,
        error_code: str = "",
        error_message: str = "",
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audio_agent_steps (
                    run_id,
                    step_name,
                    status,
                    attempt_index,
                    started_at,
                    finished_at,
                    meta_json,
                    error_code,
                    error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    step_name,
                    status,
                    attempt_index,
                    started_at,
                    finished_at,
                    json.dumps(meta or {}, ensure_ascii=False),
                    error_code or None,
                    error_message or None,
                ),
            )
            conn.execute(
                "UPDATE audio_agent_runs SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (run_id,),
            )
            conn.commit()
            step_id = int(cursor.lastrowid)
            row = conn.execute(
                """
                SELECT id, run_id, step_name, status, attempt_index, started_at, finished_at, meta_json, error_code, error_message
                FROM audio_agent_steps
                WHERE id = ?
                """,
                (step_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to load created audio agent step.")
        return self._row_to_step(row)

    def list_steps(self, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, step_name, status, attempt_index, started_at, finished_at, meta_json, error_code, error_message
                FROM audio_agent_steps
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_step(row) for row in rows]

    def add_source(
        self,
        *,
        run_id: int,
        source_type: str,
        title: str = "",
        uri: str = "",
        snippet: str = "",
        content: str = "",
        score: float = 0.0,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audio_agent_sources (
                    run_id,
                    source_type,
                    title,
                    uri,
                    snippet,
                    content,
                    score,
                    meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    source_type,
                    title or None,
                    uri or None,
                    snippet or None,
                    content or None,
                    float(score),
                    json.dumps(meta or {}, ensure_ascii=False),
                ),
            )
            conn.execute(
                "UPDATE audio_agent_runs SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (run_id,),
            )
            conn.commit()
            source_id = int(cursor.lastrowid)
            row = conn.execute(
                """
                SELECT id, run_id, source_type, title, uri, snippet, content, score, meta_json, created_at
                FROM audio_agent_sources
                WHERE id = ?
                """,
                (source_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to load created audio agent source.")
        return self._row_to_source(row)

    def list_sources(self, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, source_type, title, uri, snippet, content, score, meta_json, created_at
                FROM audio_agent_sources
                WHERE run_id = ?
                ORDER BY id ASC
                """,
                (run_id,),
            ).fetchall()
        return [self._row_to_source(row) for row in rows]

    def add_event(
        self,
        *,
        run_id: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO audio_agent_events (run_id, event_type, payload_json)
                VALUES (?, ?, ?)
                """,
                (run_id, event_type, json.dumps(payload, ensure_ascii=False)),
            )
            conn.execute(
                "UPDATE audio_agent_runs SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (run_id,),
            )
            conn.commit()
            event_id = int(cursor.lastrowid)
            row = conn.execute(
                """
                SELECT id, run_id, event_type, payload_json, created_at
                FROM audio_agent_events
                WHERE id = ?
                """,
                (event_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to load created audio agent event.")
        return self._row_to_event(row)

    def list_events(self, run_id: int, limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, run_id, event_type, payload_json, created_at
                FROM audio_agent_events
                WHERE run_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (run_id, safe_limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def update_run(
        self,
        run_id: int,
        *,
        podcast_id: int | None = None,
        status: str | None = None,
        current_step: str | None = None,
        result_payload: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        completed: bool = False,
    ) -> dict[str, Any]:
        updates: list[str] = []
        params: list[Any] = []

        if podcast_id is not None:
            updates.append("podcast_id = ?")
            params.append(int(podcast_id))
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if current_step is not None:
            updates.append("current_step = ?")
            params.append(current_step)
        if result_payload is not None:
            updates.append("result_payload = ?")
            params.append(json.dumps(result_payload, ensure_ascii=False))
        if error_code is not None:
            updates.append("error_code = ?")
            params.append(error_code or None)
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message or None)
        if completed:
            updates.append("completed_at = CURRENT_TIMESTAMP")

        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(run_id)

        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE audio_agent_runs SET " + ", ".join(updates) + " WHERE id = ?",
                params,
            )
            if cursor.rowcount < 1:
                raise ValueError(f"audio agent run not found: {run_id}")
            conn.commit()

        run = self.get_run(run_id)
        if run is None:
            raise RuntimeError("Failed to load updated audio agent run.")
        return run
