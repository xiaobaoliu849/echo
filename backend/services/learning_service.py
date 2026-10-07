"""Saved phrases + spaced review for the speaking-coach learning loop.

Learners save useful phrases or corrected sentences (usually from a
``coach_feedback`` card). Each item follows a transparent fixed-interval
schedule: a successful recall moves it one step along ``REVIEW_INTERVAL_DAYS``;
"again" resets it to the first step. New items are due immediately.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .db_utils import get_db_connection

REVIEW_INTERVAL_DAYS = (1, 3, 7, 14, 30, 60)
# Items whose next interval is at least this many days count as "learned".
LEARNED_STEP = 3
ITEM_KINDS = ("phrase", "sentence")
# Matches the speaking coach's longest correction, so any card can be saved.
MAX_ITEM_TEXT_CHARS = 1200
REVIEW_RESULTS = ("again", "good")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_item_text(text: str) -> str:
    """Dedup key: case-, width- and punctuation-insensitive."""
    folded = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.sub(r"[\W_]+", " ", folded).strip()


def next_schedule(step: int, result: str, *, now: datetime) -> tuple[int, datetime]:
    """Return (new_step, due_at) after a review."""
    if result == "again":
        return 0, now + timedelta(days=REVIEW_INTERVAL_DAYS[0])
    new_step = min(step + 1, len(REVIEW_INTERVAL_DAYS))
    interval = REVIEW_INTERVAL_DAYS[min(new_step, len(REVIEW_INTERVAL_DAYS) - 1)]
    return new_step, now + timedelta(days=interval)


class LearningItemError(ValueError):
    pass


class StaleReviewError(Exception):
    """The card was graded since the client loaded it (retry or concurrent submit)."""

    def __init__(self, item: dict[str, Any]) -> None:
        super().__init__("Review is stale.")
        self.item = item


class LearningRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or self._default_db_path()
        self._init_db()

    @staticmethod
    def _default_db_path() -> Path:
        from .config_loader import get_data_file_path

        return get_data_file_path("voice_spirit.db")

    def _connect(self) -> sqlite3.Connection:
        return get_db_connection(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    language TEXT NOT NULL DEFAULT 'English',
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL,
                    meaning TEXT NOT NULL DEFAULT '',
                    context TEXT NOT NULL DEFAULT '',
                    source_feedback_id INTEGER,
                    review_step INTEGER NOT NULL DEFAULT 0,
                    review_count INTEGER NOT NULL DEFAULT 0,
                    lapse_count INTEGER NOT NULL DEFAULT 0,
                    due_at TEXT NOT NULL,
                    last_reviewed_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE (language, kind, normalized_text)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_learning_items_due ON learning_items(due_at)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_review_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id INTEGER NOT NULL REFERENCES learning_items(id) ON DELETE CASCADE,
                    result TEXT NOT NULL,
                    step_before INTEGER NOT NULL,
                    step_after INTEGER NOT NULL,
                    reviewed_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_reviews_at ON learning_review_events(reviewed_at)"
            )
            conn.commit()

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "language": str(row["language"]),
            "kind": str(row["kind"]),
            "text": str(row["text"]),
            "meaning": str(row["meaning"] or ""),
            "context": str(row["context"] or ""),
            "source_feedback_id": row["source_feedback_id"],
            "review_step": int(row["review_step"]),
            "review_count": int(row["review_count"]),
            "lapse_count": int(row["lapse_count"]),
            "due_at": str(row["due_at"]),
            "last_reviewed_at": str(row["last_reviewed_at"] or ""),
            "created_at": str(row["created_at"]),
        }

    def _get(self, conn: sqlite3.Connection, item_id: int) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM learning_items WHERE id = ?", (int(item_id),)).fetchone()
        return self._row_to_item(row) if row else None

    def add_item(
        self,
        *,
        text: str,
        kind: str = "phrase",
        meaning: str = "",
        context: str = "",
        language: str = "English",
        source_feedback_id: int | None = None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Save an item; returns (item, created). Re-saving returns the existing item."""
        clean_text = re.sub(r"\s+", " ", str(text or "")).strip()[:MAX_ITEM_TEXT_CHARS]
        normalized = normalize_item_text(clean_text)
        if not normalized:
            raise LearningItemError("Text is required.")
        if kind not in ITEM_KINDS:
            raise LearningItemError(f"Unsupported kind: {kind}")
        clean_language = re.sub(r"\s+", " ", str(language or "")).strip()[:40] or "English"
        stamp = _iso(now or utc_now())
        lookup = (
            "SELECT * FROM learning_items WHERE language = ? AND kind = ? AND normalized_text = ?",
            (clean_language, kind, normalized),
        )
        with self._connect() as conn:
            existing = conn.execute(*lookup).fetchone()
            if existing:
                return self._row_to_item(existing), False
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO learning_items (
                        language, kind, text, normalized_text, meaning, context,
                        source_feedback_id, due_at, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_language,
                        kind,
                        clean_text,
                        normalized,
                        str(meaning or "").strip()[:MAX_ITEM_TEXT_CHARS],
                        str(context or "").strip()[:MAX_ITEM_TEXT_CHARS],
                        int(source_feedback_id) if source_feedback_id else None,
                        stamp,
                        stamp,
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # A concurrent save of the same text won the UNIQUE race.
                conn.rollback()
                existing = conn.execute(*lookup).fetchone()
                if existing is None:
                    raise
                return self._row_to_item(existing), False
            item = self._get(conn, int(cursor.lastrowid or 0))
        assert item is not None
        return item, True

    def list_items(self, *, limit: int = 200) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM learning_items ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def due_items(self, *, limit: int = 20, now: datetime | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM learning_items WHERE due_at <= ? ORDER BY due_at ASC, id ASC LIMIT ?",
                (_iso(now or utc_now()), max(1, min(int(limit), 200))),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def review(
        self,
        item_id: int,
        result: str,
        *,
        expected_review_count: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        """Grade a card. ``expected_review_count`` is the version the client saw;
        a mismatch (lost-response retry, double submit) raises StaleReviewError
        instead of promoting the card twice."""
        if result not in REVIEW_RESULTS:
            raise LearningItemError(f"Unsupported result: {result}")
        moment = now or utc_now()
        with self._connect() as conn:
            item = self._get(conn, item_id)
            if item is None:
                return None
            version = item["review_count"] if expected_review_count is None else int(expected_review_count)
            step_before = item["review_step"]
            step_after, due_at = next_schedule(step_before, result, now=moment)
            cursor = conn.execute(
                """
                UPDATE learning_items
                SET review_step = ?, due_at = ?, last_reviewed_at = ?,
                    review_count = review_count + 1,
                    lapse_count = lapse_count + ?
                WHERE id = ? AND review_count = ? AND review_step = ?
                """,
                (
                    step_after,
                    _iso(due_at),
                    _iso(moment),
                    1 if result == "again" else 0,
                    int(item_id),
                    version,
                    step_before,
                ),
            )
            if cursor.rowcount == 0:
                conn.rollback()
                current = self._get(conn, item_id)
                if current is None:
                    return None
                raise StaleReviewError(current)
            conn.execute(
                """
                INSERT INTO learning_review_events (item_id, result, step_before, step_after, reviewed_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(item_id), result, step_before, step_after, _iso(moment)),
            )
            conn.commit()
            return self._get(conn, item_id)

    def delete_item(self, item_id: int) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM learning_review_events WHERE item_id = ?", (int(item_id),))
            cursor = conn.execute("DELETE FROM learning_items WHERE id = ?", (int(item_id),))
            conn.commit()
            return cursor.rowcount > 0

    def stats(self, *, now: datetime | None = None) -> dict[str, Any]:
        moment = now or utc_now()
        # "Today" follows the machine's local calendar day, not UTC.
        day_start = _iso(moment.astimezone().replace(hour=0, minute=0, second=0, microsecond=0))
        with self._connect() as conn:
            total, due_now, learned = conn.execute(
                """
                SELECT COUNT(*),
                       COALESCE(SUM(CASE WHEN due_at <= ? THEN 1 ELSE 0 END), 0),
                       COALESCE(SUM(CASE WHEN review_step >= ? THEN 1 ELSE 0 END), 0)
                FROM learning_items
                """,
                (_iso(moment), LEARNED_STEP),
            ).fetchone()
            reviewed_today, recalled_today = conn.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(CASE WHEN result = 'good' THEN 1 ELSE 0 END), 0)
                FROM learning_review_events WHERE reviewed_at >= ?
                """,
                (day_start,),
            ).fetchone()
        return {
            "total_items": int(total),
            "due_now": int(due_now),
            "learned_items": int(learned),
            "reviewed_today": int(reviewed_today),
            "recalled_today": int(recalled_today),
        }
