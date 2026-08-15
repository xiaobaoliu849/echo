from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .agent_run_repository import AgentRunRepository
from .audio_agent_repository import ClosingConnection

logger = logging.getLogger(__name__)


class VoiceAgentSessionRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or self._default_db_path()
        self._init_db()
        self.agent_run_repository = AgentRunRepository(db_path=self.db_path)

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
        # busy_timeout first: switching journal mode below needs exclusive
        # access, and the timeout absorbs brief lock overlaps between the
        # repositories sharing this database file instead of raising
        # "database is locked".
        conn.execute("PRAGMA busy_timeout=5000")
        # WAL lets UI reads proceed while the recorder writes. It persists
        # on the database file; tolerate failure (e.g. filesystems without
        # shared-memory support) and fall back to the rollback journal
        # rather than breaking every repository call.
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            logger.debug("WAL journal mode unavailable for %s", self.db_path)
        return conn

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

    @staticmethod
    def _row_to_session(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "provider": str(row["provider"]),
            "model": str(row["model"] or ""),
            "voice": str(row["voice"] or ""),
            "status": str(row["status"]),
            "started_at": str(row["started_at"]),
            "ended_at": str(row["ended_at"] or ""),
            "meta": VoiceAgentSessionRepository._decode_json(row["meta_json"], fallback={}),
        }

    @staticmethod
    def _row_to_turn(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "session_id": str(row["session_id"]),
            "turn_id": str(row["turn_id"]),
            "user_text": str(row["user_text"] or ""),
            "assistant_text": str(row["assistant_text"] or ""),
            "memory_payload": VoiceAgentSessionRepository._decode_json(row["memory_json"], fallback={}),
            "completed": bool(row["completed"]),
            "interrupted": bool(row["interrupted"]),
            "completion_status": str(row["completion_status"] or "pending"),
            "started_at": str(row["started_at"]),
            "completed_at": str(row["completed_at"] or ""),
        }

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "session_id": str(row["session_id"]),
            "turn_id": str(row["turn_id"] or ""),
            "event_type": str(row["event_type"]),
            "tool_name": str(row["tool_name"] or ""),
            "query": str(row["query"] or ""),
            "payload": VoiceAgentSessionRepository._decode_json(row["payload_json"], fallback={}),
            "created_at": str(row["created_at"]),
        }

    @staticmethod
    def _timeline_event(
        *,
        event_id: str,
        event_type: str,
        source: str,
        timestamp: str,
        turn_id: str = "",
        tool_name: str = "",
        query: str = "",
        text: str = "",
        payload: dict[str, Any] | None = None,
        order: int,
    ) -> dict[str, Any]:
        return {
            "id": event_id,
            "event_type": event_type,
            "source": source,
            "turn_id": turn_id,
            "tool_name": tool_name,
            "query": query,
            "text": text,
            "timestamp": timestamp,
            "payload": payload or {},
            "_order": order,
        }

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_agent_sessions (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT,
                    voice TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    meta_json TEXT NOT NULL DEFAULT '{}',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    ended_at TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_agent_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    user_text TEXT,
                    assistant_text TEXT,
                    memory_json TEXT NOT NULL DEFAULT '{}',
                    completed INTEGER NOT NULL DEFAULT 0,
                    interrupted INTEGER NOT NULL DEFAULT 0,
                    completion_status TEXT NOT NULL DEFAULT 'pending',
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    UNIQUE(session_id, turn_id),
                    FOREIGN KEY(session_id) REFERENCES voice_agent_sessions(id)
                )
                """
            )
            turn_columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(voice_agent_turns)").fetchall()
            }
            if "interrupted" not in turn_columns:
                conn.execute(
                    "ALTER TABLE voice_agent_turns ADD COLUMN interrupted INTEGER NOT NULL DEFAULT 0"
                )
            if "completion_status" not in turn_columns:
                conn.execute(
                    "ALTER TABLE voice_agent_turns ADD COLUMN completion_status TEXT NOT NULL DEFAULT 'pending'"
                )
            conn.execute(
                """
                UPDATE voice_agent_turns
                SET completion_status = 'completed'
                WHERE completed = 1 AND completion_status = 'pending'
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_agent_tool_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    event_type TEXT NOT NULL,
                    tool_name TEXT,
                    query TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES voice_agent_sessions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_voice_agent_turns_session
                ON voice_agent_turns(session_id, id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_voice_agent_tool_events_session
                ON voice_agent_tool_events(session_id, id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS voice_agent_session_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_id TEXT,
                    event_type TEXT NOT NULL,
                    source TEXT NOT NULL,
                    text TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    FOREIGN KEY(session_id) REFERENCES voice_agent_sessions(id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_voice_agent_session_events_sequence
                ON voice_agent_session_events(session_id, id)
                """
            )
            conn.commit()

    def create_session(
        self,
        *,
        provider: str,
        model: str,
        voice: str,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO voice_agent_sessions (
                    id,
                    provider,
                    model,
                    voice,
                    status,
                    meta_json
                ) VALUES (?, ?, ?, ?, 'open', ?)
                """,
                (
                    session_id,
                    provider,
                    model,
                    voice,
                    self._encode_json(meta or {}),
                ),
            )
            conn.commit()
        session = self.get_session(session_id)
        if session is None:
            raise RuntimeError("Failed to load created voice agent session.")
        return session

    def finish_session(self, session_id: str, *, status: str = "closed") -> None:
        clean_status = str(status or "closed").strip() or "closed"
        timeline_enabled = self.has_session_events(session_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE voice_agent_sessions
                SET status = ?, ended_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (clean_status, str(session_id or "")),
            )
            conn.commit()
        if timeline_enabled:
            self.add_session_event(
                session_id,
                "session_closed",
                source="session",
                payload={"status": clean_status},
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, provider, model, voice, status, started_at, ended_at, meta_json
                FROM voice_agent_sessions
                WHERE id = ?
                """,
                (str(session_id or ""),),
            ).fetchone()
        return self._row_to_session(row)

    def list_sessions(self, limit: int = 20, *, provider: str = "") -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 200))
        clean_provider = str(provider or "").strip()
        with self._connect() as conn:
            if clean_provider:
                rows = conn.execute(
                    """
                    SELECT id, provider, model, voice, status, started_at, ended_at, meta_json
                    FROM voice_agent_sessions
                    WHERE lower(provider) = lower(?)
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                    """,
                    (clean_provider, safe_limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, provider, model, voice, status, started_at, ended_at, meta_json
                    FROM voice_agent_sessions
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                    """,
                    (safe_limit,),
                ).fetchall()
        return [session for row in rows if (session := self._row_to_session(row)) is not None]

    def upsert_turn(
        self,
        session_id: str,
        turn_id: str,
        *,
        user_text: str | None = None,
        assistant_text: str | None = None,
        memory_payload: dict[str, Any] | None = None,
        completed: bool = False,
        interrupted: bool | None = None,
        completion_status: str | None = None,
        fetch_turn: bool = True,
    ) -> dict[str, Any]:
        clean_turn_id = str(turn_id or "").strip()
        if not clean_turn_id:
            raise ValueError("turn_id is required.")
        effective_completion_status = completion_status
        if effective_completion_status is None and completed:
            effective_completion_status = "completed"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO voice_agent_turns (
                    session_id,
                    turn_id,
                    user_text,
                    assistant_text,
                    memory_json,
                    completed,
                    interrupted,
                    completion_status,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END)
                ON CONFLICT(session_id, turn_id) DO UPDATE SET
                    user_text = CASE
                        WHEN excluded.user_text IS NOT NULL AND excluded.user_text != '' THEN excluded.user_text
                        ELSE voice_agent_turns.user_text
                    END,
                    assistant_text = CASE
                        WHEN excluded.assistant_text IS NOT NULL AND excluded.assistant_text != '' THEN
                            COALESCE(voice_agent_turns.assistant_text, '') || excluded.assistant_text
                        ELSE voice_agent_turns.assistant_text
                    END,
                    memory_json = CASE
                        WHEN excluded.memory_json != '{}' THEN excluded.memory_json
                        ELSE voice_agent_turns.memory_json
                    END,
                    completed = CASE
                        WHEN excluded.completed = 1 THEN 1
                        ELSE voice_agent_turns.completed
                    END,
                    interrupted = CASE
                        WHEN ? IS NOT NULL THEN ?
                        ELSE voice_agent_turns.interrupted
                    END,
                    completion_status = CASE
                        WHEN ? IS NOT NULL AND ? != '' THEN ?
                        ELSE voice_agent_turns.completion_status
                    END,
                    completed_at = CASE
                        WHEN excluded.completed = 1 THEN CURRENT_TIMESTAMP
                        ELSE voice_agent_turns.completed_at
                    END
                """,
                (
                    str(session_id or ""),
                    clean_turn_id,
                    user_text,
                    assistant_text,
                    self._encode_json(memory_payload or {}),
                    1 if completed else 0,
                    1 if interrupted else 0,
                    str(effective_completion_status or "pending"),
                    1 if completed else 0,
                    None if interrupted is None else 1,
                    1 if interrupted else 0,
                    effective_completion_status,
                    effective_completion_status,
                    effective_completion_status,
                ),
            )
            conn.commit()
        if not fetch_turn:
            # High-frequency callers (per-delta assistant text flushes) don't
            # need the row back; skipping the read avoids a full-session
            # list_turns scan after every write.
            return {}
        turns = [turn for turn in self.list_turns(session_id) if turn["turn_id"] == clean_turn_id]
        if not turns:
            raise RuntimeError("Failed to load voice agent turn.")
        return turns[-1]

    def add_tool_event(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        turn_id = str(payload.get("turn_id", "") or "")
        tool_name = str(payload.get("tool_name", "") or "")
        query = str(payload.get("query", "") or "")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO voice_agent_tool_events (
                    session_id,
                    turn_id,
                    event_type,
                    tool_name,
                    query,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(session_id or ""),
                    turn_id or None,
                    str(event_type or ""),
                    tool_name or None,
                    query or None,
                    self._encode_json(payload),
                ),
            )
            conn.commit()
            event_id = int(cursor.lastrowid)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, session_id, turn_id, event_type, tool_name, query, payload_json, created_at
                FROM voice_agent_tool_events
                WHERE id = ?
                """,
                (event_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to load voice agent tool event.")
        event = self._row_to_event(row)
        if self.has_session_events(session_id):
            self.add_session_event(
                session_id,
                event_type,
                source="tool_event",
                turn_id=turn_id,
                text=str(payload.get("message") or payload.get("answer") or ""),
                payload=payload,
            )
        return event

    def rename_turn(self, session_id: str, old_turn_id: str, new_turn_id: str) -> None:
        clean_old = str(old_turn_id or "").strip()
        clean_new = str(new_turn_id or "").strip()
        if not clean_old or not clean_new or clean_old == clean_new:
            return
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT 1 FROM voice_agent_turns WHERE session_id = ? AND turn_id = ? LIMIT 1",
                (str(session_id or ""), clean_new),
            ).fetchone()
            if existing is not None:
                return
            conn.execute(
                "UPDATE voice_agent_turns SET turn_id = ? WHERE session_id = ? AND turn_id = ?",
                (clean_new, str(session_id or ""), clean_old),
            )
            conn.execute(
                "UPDATE voice_agent_session_events SET turn_id = ? WHERE session_id = ? AND turn_id = ?",
                (clean_new, str(session_id or ""), clean_old),
            )
            conn.commit()

    def has_session_events(self, session_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM voice_agent_session_events WHERE session_id = ? LIMIT 1",
                (str(session_id or ""),),
            ).fetchone()
        return row is not None

    def add_session_event(
        self,
        session_id: str,
        event_type: str,
        *,
        source: str,
        turn_id: str = "",
        text: str = "",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_payload = dict(payload or {})
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO voice_agent_session_events (
                    session_id, turn_id, event_type, source, text, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(session_id or ""),
                    str(turn_id or "") or None,
                    str(event_type or ""),
                    str(source or "session_event"),
                    str(text or "") or None,
                    self._encode_json(clean_payload),
                ),
            )
            conn.commit()
            event_id = int(cursor.lastrowid)
            row = conn.execute(
                """
                SELECT id, session_id, turn_id, event_type, source, text, payload_json, occurred_at
                FROM voice_agent_session_events
                WHERE id = ?
                """,
                (event_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("Failed to load voice agent session event.")
        return {
            "id": int(row["id"]),
            "session_id": str(row["session_id"]),
            "turn_id": str(row["turn_id"] or ""),
            "event_type": str(row["event_type"]),
            "source": str(row["source"]),
            "text": str(row["text"] or ""),
            "payload": self._decode_json(row["payload_json"], fallback={}),
            "occurred_at": str(row["occurred_at"]),
        }

    def list_session_events(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, turn_id, event_type, source, text, payload_json, occurred_at
                FROM voice_agent_session_events
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (str(session_id or ""),),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "session_id": str(row["session_id"]),
                "turn_id": str(row["turn_id"] or ""),
                "event_type": str(row["event_type"]),
                "source": str(row["source"]),
                "text": str(row["text"] or ""),
                "payload": self._decode_json(row["payload_json"], fallback={}),
                "occurred_at": str(row["occurred_at"]),
            }
            for row in rows
        ]

    def list_turns(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    id,
                    session_id,
                    turn_id,
                    user_text,
                    assistant_text,
                    memory_json,
                    completed,
                    interrupted,
                    completion_status,
                    started_at,
                    completed_at
                FROM voice_agent_turns
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (str(session_id or ""),),
            ).fetchall()
        return [self._row_to_turn(row) for row in rows]

    def list_tool_events(self, session_id: str, limit: int = 200) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 1000))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, session_id, turn_id, event_type, tool_name, query, payload_json, created_at
                FROM voice_agent_tool_events
                WHERE session_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (str(session_id or ""), safe_limit),
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def link_agent_run_artifact(
        self,
        session_id: str,
        turn_id: str,
        artifact: dict[str, Any],
        *,
        relation_type: str = "created_by",
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if str(artifact.get("type", "")) != "audio_agent_run":
            raise ValueError("Unsupported agent run artifact type.")
        run = self.agent_run_repository.upsert_audio_artifact(artifact)
        return self.agent_run_repository.link_voice_turn(
            agent_run_id=str(run["id"]),
            voice_session_id=str(session_id or ""),
            voice_turn_id=str(turn_id or ""),
            relation_type=relation_type,
            meta=meta,
        )

    def list_agent_run_links(self, session_id: str) -> list[dict[str, Any]]:
        return self.agent_run_repository.list_links_for_session(session_id)

    @staticmethod
    def _parse_timestamp(value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    @staticmethod
    def _metric_summary(samples: list[float]) -> dict[str, int | None]:
        clean = sorted(max(0.0, float(sample)) for sample in samples)
        if not clean:
            return {"count": 0, "avg": None, "p50": None, "p95": None, "min": None, "max": None}

        def percentile(fraction: float) -> int:
            if len(clean) == 1:
                return round(clean[0])
            position = (len(clean) - 1) * fraction
            lower = int(position)
            upper = min(lower + 1, len(clean) - 1)
            weight = position - lower
            return round(clean[lower] * (1 - weight) + clean[upper] * weight)

        return {
            "count": len(clean),
            "avg": round(sum(clean) / len(clean)),
            "p50": percentile(0.5),
            "p95": percentile(0.95),
            "min": round(clean[0]),
            "max": round(clean[-1]),
        }

    def summarize_metrics(
        self,
        *,
        limit: int = 200,
        provider: str = "",
    ) -> dict[str, Any]:
        sessions = self.list_sessions(limit=limit, provider=provider)

        def empty_bucket() -> dict[str, Any]:
            return {
                "session_count": 0,
                "turn_count": 0,
                "completed_turn_count": 0,
                "interrupted_turn_count": 0,
                "decision_events": [],
                "first_audio_samples": [],
                "decision_samples": [],
                "stop_samples": [],
                "turn_completion_samples": [],
            }

        total = empty_bucket()
        provider_buckets: dict[str, dict[str, Any]] = {}

        for session in sessions:
            provider_name = str(session.get("provider", "") or "Unknown")
            buckets = (total, provider_buckets.setdefault(provider_name, empty_bucket()))
            for bucket in buckets:
                bucket["session_count"] += 1

            turns = self.list_turns(str(session["id"]))
            fallback_turn_durations: dict[str, float] = {}
            for turn in turns:
                started_at = self._parse_timestamp(turn.get("started_at"))
                completed_at = self._parse_timestamp(turn.get("completed_at"))
                duration_ms = None
                if started_at is not None and completed_at is not None:
                    try:
                        duration_ms = max(0.0, (completed_at - started_at).total_seconds() * 1000)
                    except TypeError:
                        duration_ms = None
                for bucket in buckets:
                    bucket["turn_count"] += 1
                    if turn.get("completed"):
                        bucket["completed_turn_count"] += 1
                    if turn.get("interrupted"):
                        bucket["interrupted_turn_count"] += 1
                if duration_ms is not None:
                    fallback_turn_durations[str(turn.get("turn_id", ""))] = duration_ms

            session_events = self.list_session_events(str(session["id"]))
            superseded_candidates = {
                str((event.get("payload") or {}).get("supersedes_candidate_id", ""))
                for event in session_events
                if event.get("event_type") == "interruption_decision"
                and isinstance(event.get("payload"), dict)
                and (event.get("payload") or {}).get("supersedes_candidate_id")
            }
            true_barge_in_candidates = {
                str((event.get("payload") or {}).get("candidate_id", ""))
                for event in session_events
                if event.get("event_type") == "interruption_decision"
                and isinstance(event.get("payload"), dict)
                and str((event.get("payload") or {}).get("candidate_id", "")) not in superseded_candidates
                and (event.get("payload") or {}).get("classification") == "TRUE_BARGE_IN"
            }
            true_barge_in_candidates.discard("")
            turn_started_at: dict[str, datetime] = {}
            canonical_completion_turn_ids: set[str] = set()
            recorded_stop_candidates: set[str] = set()
            for event in session_events:
                payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                event_type = str(event.get("event_type", ""))
                event_turn_id = str(event.get("turn_id", ""))
                event_timestamp = self._parse_timestamp(event.get("occurred_at"))
                if event_type == "user_transcript" and event_turn_id and event_timestamp is not None:
                    turn_started_at[event_turn_id] = event_timestamp
                elif (
                    event_type in {"turn_completed", "turn_interrupted"}
                    and event_turn_id
                    and event_turn_id not in canonical_completion_turn_ids
                ):
                    started_at = turn_started_at.get(event_turn_id)
                    if started_at is not None and event_timestamp is not None:
                        try:
                            duration_ms = max(0.0, (event_timestamp - started_at).total_seconds() * 1000)
                        except TypeError:
                            duration_ms = None
                        if duration_ms is not None:
                            canonical_completion_turn_ids.add(event_turn_id)
                            for bucket in buckets:
                                bucket["turn_completion_samples"].append(duration_ms)
                if event_type == "assistant_audio_started":
                    value = payload.get("first_audio_ms", payload.get("elapsed_ms"))
                    if isinstance(value, (int, float)):
                        for bucket in buckets:
                            bucket["first_audio_samples"].append(float(value))
                elif event_type == "interruption_decision":
                    candidate_id = str(payload.get("candidate_id", ""))
                    if candidate_id and candidate_id in superseded_candidates:
                        continue
                    for bucket in buckets:
                        bucket["decision_events"].append(payload)
                    value = payload.get("decision_latency_ms", payload.get("elapsed_ms"))
                    if isinstance(value, (int, float)):
                        for bucket in buckets:
                            bucket["decision_samples"].append(float(value))
                elif event_type == "interruption_client_stopped":
                    stop_candidate_id = str(payload.get("candidate_id", ""))
                    if (
                        stop_candidate_id not in true_barge_in_candidates
                        or stop_candidate_id in recorded_stop_candidates
                    ):
                        continue
                    value = payload.get("stop_latency_ms")
                    if isinstance(value, (int, float)):
                        recorded_stop_candidates.add(stop_candidate_id)
                        for bucket in buckets:
                            bucket["stop_samples"].append(float(value))

            # Historical sessions may predate the canonical event ledger. Use
            # their coarser turn-table timestamps only when no precise event
            # pair exists for that turn.
            for turn_id, duration_ms in fallback_turn_durations.items():
                if turn_id in canonical_completion_turn_ids:
                    continue
                for bucket in buckets:
                    bucket["turn_completion_samples"].append(duration_ms)

        def finalize(bucket: dict[str, Any]) -> dict[str, Any]:
            decisions = list(bucket.pop("decision_events"))
            classifications = {
                "TRUE_BARGE_IN": 0,
                "BACKCHANNEL": 0,
                "NOISE_OR_SILENCE": 0,
            }
            for decision in decisions:
                classification = str(decision.get("classification", ""))
                if classification in classifications:
                    classifications[classification] += 1
            decision_count = sum(classifications.values())
            result = {
                "session_count": int(bucket["session_count"]),
                "turn_count": int(bucket["turn_count"]),
                "completed_turn_count": int(bucket["completed_turn_count"]),
                "interrupted_turn_count": int(bucket["interrupted_turn_count"]),
                "decision_count": decision_count,
                "classifications": classifications,
                "false_interruption_rate": (
                    (classifications["BACKCHANNEL"] + classifications["NOISE_OR_SILENCE"])
                    / decision_count
                    if decision_count
                    else None
                ),
                "first_audio_ms": self._metric_summary(bucket.pop("first_audio_samples")),
                "interruption_decision_ms": self._metric_summary(bucket.pop("decision_samples")),
                "interruption_stop_ms": self._metric_summary(bucket.pop("stop_samples")),
                "turn_completion_ms": self._metric_summary(bucket.pop("turn_completion_samples")),
            }
            return result

        summary = finalize(total)
        summary["providers"] = [
            {"provider": provider_name, **finalize(bucket)}
            for provider_name, bucket in sorted(provider_buckets.items())
        ]
        return summary

    def build_timeline(self, session_id: str) -> list[dict[str, Any]]:
        session = self.get_session(session_id)
        if session is None:
            return []

        provider = str(session.get("provider", ""))
        meta = session.get("meta") or {}
        transport = str(meta.get("transport", "websocket") if isinstance(meta, dict) else "websocket")
        session_events = self.list_session_events(session_id)
        if session_events:
            canonical_timeline: list[dict[str, Any]] = []
            for event in session_events:
                payload = event.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {}
                item = self._timeline_event(
                    event_id=f"session_event:{event['id']}",
                    event_type=str(event.get("event_type", "")),
                    source=str(event.get("source", "session_event")),
                    turn_id=str(event.get("turn_id", "")),
                    tool_name=str(payload.get("tool_name", "")),
                    query=str(payload.get("query", "")),
                    text=str(event.get("text", "")),
                    timestamp=str(event.get("occurred_at", "")),
                    payload=payload,
                    order=int(event["id"]),
                )
                item.pop("_order", None)
                item["sequence_no"] = int(event["id"])
                item["provider"] = provider
                item["transport"] = transport
                if "elapsed_ms" in payload:
                    item["elapsed_ms"] = payload["elapsed_ms"]
                if "stage" in payload:
                    item["stage"] = payload["stage"]
                canonical_timeline.append(item)
            return canonical_timeline

        timeline: list[dict[str, Any]] = [
            self._timeline_event(
                event_id=f"session:{session['id']}:open",
                event_type="session_open",
                source="session",
                timestamp=str(session.get("started_at", "")),
                payload={
                    "provider": session.get("provider", ""),
                    "model": session.get("model", ""),
                    "voice": session.get("voice", ""),
                    "status": session.get("status", ""),
                    "meta": session.get("meta", {}),
                },
                order=0,
            )
        ]

        for turn in self.list_turns(session_id):
            turn_id = str(turn.get("turn_id", ""))
            if str(turn.get("user_text", "")).strip():
                timeline.append(
                    self._timeline_event(
                        event_id=f"turn:{turn['id']}:user",
                        event_type="user_transcript",
                        source="turn",
                        turn_id=turn_id,
                        text=str(turn.get("user_text", "")),
                        timestamp=str(turn.get("started_at", "")),
                        payload={"completed": bool(turn.get("completed", False))},
                        order=20,
                    )
                )
            if str(turn.get("assistant_text", "")).strip():
                timeline.append(
                    self._timeline_event(
                        event_id=f"turn:{turn['id']}:assistant",
                        event_type="assistant_response",
                        source="turn",
                        turn_id=turn_id,
                        text=str(turn.get("assistant_text", "")),
                        timestamp=str(turn.get("completed_at") or turn.get("started_at", "")),
                        payload={
                            "completed": bool(turn.get("completed", False)),
                            "interrupted": bool(turn.get("interrupted", False)),
                            "status": str(turn.get("completion_status", "pending")),
                        },
                        order=60,
                    )
                )
            memory_payload = turn.get("memory_payload", {})
            if isinstance(memory_payload, dict) and memory_payload:
                timeline.append(
                    self._timeline_event(
                        event_id=f"turn:{turn['id']}:memory",
                        event_type="memory_commit",
                        source="memory",
                        turn_id=turn_id,
                        timestamp=str(turn.get("completed_at") or turn.get("started_at", "")),
                        payload=memory_payload,
                        order=70,
                    )
                )
            if bool(turn.get("completed", False)):
                timeline.append(
                    self._timeline_event(
                        event_id=f"turn:{turn['id']}:complete",
                        event_type=(
                            "turn_interrupted"
                            if bool(turn.get("interrupted", False))
                            else "turn_completed"
                        ),
                        source="turn",
                        turn_id=turn_id,
                        timestamp=str(turn.get("completed_at") or turn.get("started_at", "")),
                        payload={
                            "interrupted": bool(turn.get("interrupted", False)),
                            "status": str(turn.get("completion_status", "completed")),
                        },
                        order=80,
                    )
                )

        for event in self.list_tool_events(session_id):
            payload = event.get("payload", {})
            timeline.append(
                self._timeline_event(
                    event_id=f"tool_event:{event['id']}",
                    event_type=str(event.get("event_type", "")),
                    source="tool_event",
                    turn_id=str(event.get("turn_id", "")),
                    tool_name=str(event.get("tool_name", "")),
                    query=str(event.get("query", "")),
                    text=str(payload.get("message") or payload.get("answer") or "") if isinstance(payload, dict) else "",
                    timestamp=str(event.get("created_at", "")),
                    payload=payload if isinstance(payload, dict) else {},
                    order=40,
                )
            )

        if str(session.get("ended_at", "")).strip():
            timeline.append(
                self._timeline_event(
                    event_id=f"session:{session['id']}:closed",
                    event_type="session_closed",
                    source="session",
                    timestamp=str(session.get("ended_at", "")),
                    payload={"status": session.get("status", "")},
                    order=900,
                )
            )

        timeline.sort(
            key=lambda item: (
                str(item.get("timestamp", "")),
                int(item.get("_order", 0)),
                str(item.get("id", "")),
            )
        )
        for item in timeline:
            item.pop("_order", None)
            item["provider"] = provider
            item["transport"] = transport
            if "elapsed_ms" in item["payload"]:
                item["elapsed_ms"] = item["payload"]["elapsed_ms"]
            if "stage" in item["payload"]:
                item["stage"] = item["payload"]["stage"]
        return timeline
