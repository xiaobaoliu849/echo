from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .db_utils import ClosingConnection, get_db_connection


class AgentRunRepository:
    """Canonical projection and durable links for heterogeneous agent runs."""

    AUDIO_RUN_TYPE = "audio_agent"

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or self._default_db_path()
        self._init_db()
        self._backfill_existing_audio_runs()
        self._backfill_existing_voice_links()

    @staticmethod
    def _default_db_path() -> Path:
        from .config_loader import get_data_file_path

        return get_data_file_path("voice_spirit.db")

    def _connect(self) -> sqlite3.Connection:
        return get_db_connection(self.db_path)

    @staticmethod
    def canonical_audio_run_id(source_run_id: int | str) -> str:
        clean_id = str(source_run_id or "").strip()
        if not clean_id:
            raise ValueError("source audio run id is required.")
        return f"audio_agent:{clean_id}"

    @staticmethod
    def _encode_json(value: Any) -> str:
        return json.dumps(value if value is not None else {}, ensure_ascii=False)

    @staticmethod
    def _decode_json(value: Any, *, fallback: Any) -> Any:
        if isinstance(value, str) and value.strip():
            try:
                return json.loads(value)
            except Exception:
                return fallback
        return fallback

    @classmethod
    def _row_to_run(cls, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "run_type": str(row["run_type"]),
            "source_kind": str(row["source_kind"]),
            "source_run_id": str(row["source_run_id"]),
            "title": str(row["title"] or ""),
            "status": str(row["status"]),
            "current_step": str(row["current_step"] or ""),
            "provider": str(row["provider"] or ""),
            "model": str(row["model"] or ""),
            "input_payload": cls._decode_json(row["input_json"], fallback={}),
            "result_payload": cls._decode_json(row["result_json"], fallback={}),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
            "completed_at": str(row["completed_at"] or ""),
        }

    @classmethod
    def _row_to_link(cls, row: sqlite3.Row) -> dict[str, Any]:
        run = {
            "id": str(row["run_id"]),
            "run_type": str(row["run_type"]),
            "source_kind": str(row["source_kind"]),
            "source_run_id": str(row["source_run_id"]),
            "title": str(row["title"] or ""),
            "status": str(row["status"]),
            "current_step": str(row["current_step"] or ""),
            "provider": str(row["provider"] or ""),
            "model": str(row["model"] or ""),
            "input_payload": cls._decode_json(row["input_json"], fallback={}),
            "result_payload": cls._decode_json(row["result_json"], fallback={}),
            "created_at": str(row["run_created_at"] or ""),
            "updated_at": str(row["run_updated_at"] or ""),
            "completed_at": str(row["completed_at"] or ""),
        }
        return {
            "id": int(row["link_id"]),
            "agent_run_id": str(row["run_id"]),
            "voice_session_id": str(row["voice_session_id"]),
            "voice_turn_id": str(row["voice_turn_id"]),
            "relation_type": str(row["relation_type"]),
            "meta": cls._decode_json(row["link_meta_json"], fallback={}),
            "created_at": str(row["link_created_at"]),
            "run": run,
        }

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    title TEXT,
                    status TEXT NOT NULL,
                    current_step TEXT,
                    provider TEXT,
                    model TEXT,
                    input_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    completed_at TEXT,
                    UNIQUE(source_kind, source_run_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_run_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_run_id TEXT NOT NULL,
                    voice_session_id TEXT NOT NULL,
                    voice_turn_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL DEFAULT 'created_by',
                    meta_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    UNIQUE(agent_run_id, voice_session_id, voice_turn_id, relation_type),
                    FOREIGN KEY(agent_run_id) REFERENCES agent_runs(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_runs_updated
                ON agent_runs(updated_at DESC, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_run_links_voice
                ON agent_run_links(voice_session_id, voice_turn_id, id)
                """
            )
            conn.commit()

    def upsert_run(
        self,
        *,
        run_id: str,
        run_type: str,
        source_kind: str,
        source_run_id: str,
        title: str,
        status: str,
        current_step: str = "",
        provider: str = "",
        model: str = "",
        input_payload: dict[str, Any] | None = None,
        result_payload: dict[str, Any] | None = None,
        created_at: str = "",
        updated_at: str = "",
        completed_at: str = "",
    ) -> dict[str, Any]:
        clean_run_id = str(run_id or "").strip()
        clean_source_run_id = str(source_run_id or "").strip()
        if not clean_run_id or not clean_source_run_id:
            raise ValueError("canonical run id and source run id are required.")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (
                    id, run_type, source_kind, source_run_id, title, status,
                    current_step, provider, model, input_json, result_json,
                    created_at, updated_at, completed_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    COALESCE(NULLIF(?, ''), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    COALESCE(NULLIF(?, ''), strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    NULLIF(?, '')
                )
                ON CONFLICT(id) DO UPDATE SET
                    run_type = excluded.run_type,
                    source_kind = excluded.source_kind,
                    source_run_id = excluded.source_run_id,
                    title = CASE WHEN excluded.title != '' THEN excluded.title ELSE agent_runs.title END,
                    status = excluded.status,
                    current_step = CASE WHEN excluded.current_step != '' THEN excluded.current_step ELSE agent_runs.current_step END,
                    provider = CASE WHEN excluded.provider != '' THEN excluded.provider ELSE agent_runs.provider END,
                    model = CASE WHEN excluded.model != '' THEN excluded.model ELSE agent_runs.model END,
                    input_json = CASE WHEN excluded.input_json != '{}' THEN excluded.input_json ELSE agent_runs.input_json END,
                    result_json = CASE WHEN excluded.result_json != '{}' THEN excluded.result_json ELSE agent_runs.result_json END,
                    updated_at = excluded.updated_at,
                    completed_at = COALESCE(excluded.completed_at, agent_runs.completed_at)
                """,
                (
                    clean_run_id,
                    str(run_type or source_kind or "agent"),
                    str(source_kind or run_type or "agent"),
                    clean_source_run_id,
                    str(title or ""),
                    str(status or "queued"),
                    str(current_step or ""),
                    str(provider or ""),
                    str(model or ""),
                    self._encode_json(input_payload or {}),
                    self._encode_json(result_payload or {}),
                    str(created_at or ""),
                    str(updated_at or ""),
                    str(completed_at or ""),
                ),
            )
            conn.commit()
        run = self.get_run(clean_run_id)
        if run is None:
            raise RuntimeError("Failed to load canonical agent run.")
        return run

    def upsert_audio_run(self, run: dict[str, Any]) -> dict[str, Any]:
        source_run_id = str(run.get("id", "") or "").strip()
        return self.upsert_run(
            run_id=self.canonical_audio_run_id(source_run_id),
            run_type=self.AUDIO_RUN_TYPE,
            source_kind=self.AUDIO_RUN_TYPE,
            source_run_id=source_run_id,
            title=str(run.get("topic", "")),
            status=str(run.get("status", "queued")),
            current_step=str(run.get("current_step", "")),
            provider=str(run.get("provider", "")),
            model=str(run.get("model", "")),
            input_payload=run.get("input_payload") if isinstance(run.get("input_payload"), dict) else {},
            result_payload=run.get("result_payload") if isinstance(run.get("result_payload"), dict) else {},
            created_at=str(run.get("created_at", "")),
            updated_at=str(run.get("updated_at", "")),
            completed_at=str(run.get("completed_at", "")),
        )

    def upsert_audio_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        source_run_id = str(artifact.get("run_id", "") or "").strip()
        return self.upsert_run(
            run_id=self.canonical_audio_run_id(source_run_id),
            run_type=self.AUDIO_RUN_TYPE,
            source_kind=self.AUDIO_RUN_TYPE,
            source_run_id=source_run_id,
            title=str(artifact.get("topic", "")),
            status=str(artifact.get("status", "queued")),
            current_step=str(artifact.get("current_step", "")),
            provider=str(artifact.get("provider", "")),
            model=str(artifact.get("model", "")),
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, run_type, source_kind, source_run_id, title, status,
                       current_step, provider, model, input_json, result_json,
                       created_at, updated_at, completed_at
                FROM agent_runs
                WHERE id = ?
                """,
                (str(run_id or ""),),
            ).fetchone()
        return self._row_to_run(row)

    def list_runs(self, limit: int = 50, *, run_type: str = "") -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        clean_type = str(run_type or "").strip()
        query = (
            "SELECT id, run_type, source_kind, source_run_id, title, status, "
            "current_step, provider, model, input_json, result_json, "
            "created_at, updated_at, completed_at FROM agent_runs"
        )
        params: list[Any] = []
        if clean_type:
            query += " WHERE run_type = ?"
            params.append(clean_type)
        query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        params.append(safe_limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [item for row in rows if (item := self._row_to_run(row)) is not None]

    def link_voice_turn(
        self,
        *,
        agent_run_id: str,
        voice_session_id: str,
        voice_turn_id: str,
        relation_type: str = "created_by",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_agent_run_id = str(agent_run_id or "").strip()
        clean_session_id = str(voice_session_id or "").strip()
        clean_turn_id = str(voice_turn_id or "").strip()
        if not clean_agent_run_id or not clean_session_id or not clean_turn_id:
            raise ValueError("agent_run_id, voice_session_id, and voice_turn_id are required.")
        with self._connect() as conn:
            if conn.execute("SELECT 1 FROM agent_runs WHERE id = ?", (clean_agent_run_id,)).fetchone() is None:
                raise ValueError(f"agent run not found: {clean_agent_run_id}")
            conn.execute(
                """
                INSERT INTO agent_run_links (
                    agent_run_id, voice_session_id, voice_turn_id, relation_type, meta_json
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(agent_run_id, voice_session_id, voice_turn_id, relation_type)
                DO UPDATE SET meta_json = excluded.meta_json
                """,
                (
                    clean_agent_run_id,
                    clean_session_id,
                    clean_turn_id,
                    str(relation_type or "created_by"),
                    self._encode_json(meta or {}),
                ),
            )
            conn.commit()
            # sqlite3.lastrowid can still point at an earlier INSERT when the
            # UPSERT took its conflict/update path. Resolve the durable key by
            # its unique identity so repeated links always return the same row.
            row = conn.execute(
                """
                SELECT id FROM agent_run_links
                WHERE agent_run_id = ? AND voice_session_id = ?
                  AND voice_turn_id = ? AND relation_type = ?
                """,
                (
                    clean_agent_run_id,
                    clean_session_id,
                    clean_turn_id,
                    str(relation_type or "created_by"),
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Failed to load linked agent run.")
            link_id = int(row["id"])
        links = self._list_links("WHERE links.id = ?", [link_id])
        if not links:
            raise RuntimeError("Failed to load linked agent run.")
        return links[0]

    def _list_links(self, where: str, params: list[Any]) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    links.id AS link_id,
                    links.agent_run_id AS run_id,
                    links.voice_session_id,
                    links.voice_turn_id,
                    links.relation_type,
                    links.meta_json AS link_meta_json,
                    links.created_at AS link_created_at,
                    runs.run_type,
                    runs.source_kind,
                    runs.source_run_id,
                    runs.title,
                    runs.status,
                    runs.current_step,
                    runs.provider,
                    runs.model,
                    runs.input_json,
                    runs.result_json,
                    runs.created_at AS run_created_at,
                    runs.updated_at AS run_updated_at,
                    runs.completed_at
                FROM agent_run_links AS links
                JOIN agent_runs AS runs ON runs.id = links.agent_run_id
                {where}
                ORDER BY links.id ASC
                """,
                params,
            ).fetchall()
        return [self._row_to_link(row) for row in rows]

    def refresh_audio_run(self, source_run_id: int | str) -> dict[str, Any] | None:
        """Refresh one projection from the existing audio-agent source table."""
        clean_source_id = str(source_run_id or "").strip()
        if not clean_source_id:
            return None
        try:
            numeric_source_id = int(clean_source_id)
        except ValueError:
            return None
        with self._connect() as conn:
            if not self._table_exists(conn, "audio_agent_runs"):
                return None
            row = conn.execute(
                """
                SELECT id, topic, status, current_step, provider, model,
                       input_payload, result_payload, created_at, updated_at, completed_at
                FROM audio_agent_runs
                WHERE id = ?
                """,
                (numeric_source_id,),
            ).fetchone()
        if row is None:
            return None
        return self.upsert_audio_run(
            {
                "id": int(row["id"]),
                "topic": str(row["topic"] or ""),
                "status": str(row["status"] or "queued"),
                "current_step": str(row["current_step"] or ""),
                "provider": str(row["provider"] or ""),
                "model": str(row["model"] or ""),
                "input_payload": self._decode_json(row["input_payload"], fallback={}),
                "result_payload": self._decode_json(row["result_payload"], fallback={}),
                "created_at": str(row["created_at"] or ""),
                "updated_at": str(row["updated_at"] or ""),
                "completed_at": str(row["completed_at"] or ""),
            }
        )

    def _refresh_linked_audio_runs(self, links: list[dict[str, Any]]) -> bool:
        refreshed = False
        for link in links:
            run = link.get("run") if isinstance(link, dict) else None
            if not isinstance(run, dict) or run.get("source_kind") != self.AUDIO_RUN_TYPE:
                continue
            refreshed = self.refresh_audio_run(run.get("source_run_id", "")) is not None or refreshed
        return refreshed

    def list_links_for_session(self, voice_session_id: str) -> list[dict[str, Any]]:
        params = [str(voice_session_id or "")]
        links = self._list_links(
            "WHERE links.voice_session_id = ?",
            params,
        )
        return self._list_links("WHERE links.voice_session_id = ?", params) if self._refresh_linked_audio_runs(links) else links

    def list_links_for_run(self, agent_run_id: str) -> list[dict[str, Any]]:
        params = [str(agent_run_id or "")]
        links = self._list_links(
            "WHERE links.agent_run_id = ?",
            params,
        )
        return self._list_links("WHERE links.agent_run_id = ?", params) if self._refresh_linked_audio_runs(links) else links

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone() is not None

    def _backfill_existing_audio_runs(self) -> None:
        with self._connect() as conn:
            if not self._table_exists(conn, "audio_agent_runs"):
                return
            rows = conn.execute(
                """
                SELECT id, topic, status, current_step, provider, model,
                       input_payload, result_payload, created_at, updated_at, completed_at
                FROM audio_agent_runs
                ORDER BY id ASC
                """
            ).fetchall()
        for row in rows:
            self.upsert_audio_run(
                {
                    "id": int(row["id"]),
                    "topic": str(row["topic"] or ""),
                    "status": str(row["status"] or "queued"),
                    "current_step": str(row["current_step"] or ""),
                    "provider": str(row["provider"] or ""),
                    "model": str(row["model"] or ""),
                    "input_payload": self._decode_json(row["input_payload"], fallback={}),
                    "result_payload": self._decode_json(row["result_payload"], fallback={}),
                    "created_at": str(row["created_at"] or ""),
                    "updated_at": str(row["updated_at"] or ""),
                    "completed_at": str(row["completed_at"] or ""),
                }
            )

    def _backfill_existing_voice_links(self) -> None:
        with self._connect() as conn:
            if not self._table_exists(conn, "voice_agent_tool_events"):
                return
            rows = conn.execute(
                """
                SELECT session_id, turn_id, payload_json
                FROM voice_agent_tool_events
                WHERE event_type = 'agent_result'
                ORDER BY id ASC
                """
            ).fetchall()
        for row in rows:
            payload = self._decode_json(row["payload_json"], fallback={})
            artifact = payload.get("artifact") if isinstance(payload, dict) else None
            if not isinstance(artifact, dict) or artifact.get("type") != "audio_agent_run":
                continue
            session_id = str(row["session_id"] or "")
            turn_id = str(row["turn_id"] or "")
            if not session_id or not turn_id or not artifact.get("run_id"):
                continue
            canonical_id = self.canonical_audio_run_id(artifact["run_id"])
            # Audio source rows are backfilled first and carry the authoritative
            # lifecycle state. Historical voice artifacts are snapshots and
            # must only create a projection when the source row is unavailable.
            run = self.get_run(canonical_id) or self.upsert_audio_artifact(artifact)
            self.link_voice_turn(
                agent_run_id=str(run["id"]),
                voice_session_id=session_id,
                voice_turn_id=turn_id,
                meta={"backfilled": True, "tool_name": "create_audio_agent_run"},
            )
