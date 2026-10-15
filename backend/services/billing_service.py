"""Per-user realtime minutes balance for hosted mode.

Balances are kept in whole seconds. Every change is written to
``billing_ledger`` in the same transaction as the balance update, so the
balance can always be reconciled against its history.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .db_utils import get_db_connection


class BillingService:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or self._default_db_path()
        self._init_db()

    @staticmethod
    def _default_db_path() -> Path:
        from .config_loader import get_data_file_path

        return get_data_file_path("voice_spirit.db")

    def _connect(self):
        return get_db_connection(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS billing_balances (
                    user_email TEXT PRIMARY KEY,
                    balance_seconds INTEGER NOT NULL DEFAULT 0,
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS billing_ledger (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    delta_seconds INTEGER NOT NULL,
                    wall_seconds INTEGER NOT NULL DEFAULT 0,
                    provider TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_billing_ledger_user ON billing_ledger(user_email, created_at)"
            )
            conn.commit()

    @staticmethod
    def _normalize(email: str) -> str:
        return str(email or "").strip().lower()

    def get_balance(self, email: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT balance_seconds FROM billing_balances WHERE user_email = ?",
                (self._normalize(email),),
            ).fetchone()
        return int(row["balance_seconds"]) if row else 0

    def _apply(
        self,
        email: str,
        delta_seconds: int,
        *,
        kind: str,
        wall_seconds: int = 0,
        provider: str = "",
        model: str = "",
        note: str = "",
    ) -> int:
        user = self._normalize(email)
        now = int(time.time())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT balance_seconds FROM billing_balances WHERE user_email = ?",
                (user,),
            ).fetchone()
            current = int(row["balance_seconds"]) if row else 0
            # Usage never drives the balance negative; the meter hangs up at 0,
            # so any overshoot is at most one metering tick.
            new_balance = max(0, current + int(delta_seconds))
            applied = new_balance - current
            conn.execute(
                """
                INSERT INTO billing_balances (user_email, balance_seconds, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_email) DO UPDATE SET
                    balance_seconds = excluded.balance_seconds,
                    updated_at = excluded.updated_at
                """,
                (user, new_balance, now),
            )
            conn.execute(
                """
                INSERT INTO billing_ledger
                    (user_email, kind, delta_seconds, wall_seconds, provider, model, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user, kind, applied, int(wall_seconds), provider, model, note, now),
            )
            conn.commit()
        return new_balance

    def grant(self, email: str, seconds: int, *, note: str = "") -> int:
        if int(seconds) == 0:
            raise ValueError("Grant amount must be non-zero.")
        return self._apply(email, int(seconds), kind="grant", note=note)

    def charge(
        self,
        email: str,
        billed_seconds: int,
        *,
        wall_seconds: int,
        provider: str,
        model: str,
    ) -> int:
        if billed_seconds <= 0:
            return self.get_balance(email)
        return self._apply(
            email,
            -int(billed_seconds),
            kind="usage",
            wall_seconds=wall_seconds,
            provider=provider,
            model=model,
        )

    def usage_summary(self, *, since: int = 0) -> list[dict[str, Any]]:
        """Per-user balance plus wall-clock usage since ``since`` (epoch secs)."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT b.user_email AS user_email,
                       b.balance_seconds AS balance_seconds,
                       COALESCE(SUM(CASE WHEN l.kind = 'usage' THEN l.wall_seconds END), 0) AS used_seconds,
                       MAX(CASE WHEN l.kind = 'usage' THEN l.created_at END) AS last_used_at
                FROM billing_balances b
                LEFT JOIN billing_ledger l
                       ON l.user_email = b.user_email AND l.created_at >= ?
                GROUP BY b.user_email
                ORDER BY b.user_email
                """,
                (int(since),),
            ).fetchall()
        return [
            {
                "user_email": str(r["user_email"]),
                "balance_seconds": int(r["balance_seconds"]),
                "used_seconds": int(r["used_seconds"] or 0),
                "last_used_at": int(r["last_used_at"]) if r["last_used_at"] else None,
            }
            for r in rows
        ]

    def usage_by_model(self, *, since: int = 0) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT provider, model, SUM(wall_seconds) AS wall_seconds, COUNT(*) AS ticks
                FROM billing_ledger
                WHERE kind = 'usage' AND created_at >= ?
                GROUP BY provider, model
                ORDER BY wall_seconds DESC
                """,
                (int(since),),
            ).fetchall()
        return [
            {"provider": str(r["provider"]), "model": str(r["model"]), "wall_seconds": int(r["wall_seconds"] or 0)}
            for r in rows
        ]


    def usage_by_day(self, *, since: int = 0, utc_offset_minutes: int = 0, email: str = "") -> list[dict[str, Any]]:
        """Daily wall-clock and billed usage, bucketed in the viewer's timezone."""
        shift = f"{int(utc_offset_minutes):+d} minutes"
        query = """
            SELECT date(created_at, 'unixepoch', ?) AS day,
                   SUM(wall_seconds) AS wall_seconds,
                   -SUM(delta_seconds) AS billed_seconds,
                   COUNT(DISTINCT user_email) AS users
            FROM billing_ledger
            WHERE kind = 'usage' AND created_at >= ?
        """
        params: list[Any] = [shift, int(since)]
        if email:
            query += " AND user_email = ?"
            params.append(self._normalize(email))
        query += " GROUP BY day ORDER BY day"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "day": str(r["day"]),
                "wall_seconds": int(r["wall_seconds"] or 0),
                "billed_seconds": int(r["billed_seconds"] or 0),
                "users": int(r["users"] or 0),
            }
            for r in rows
        ]

    def grants(self, email: str, *, limit: int = 50) -> list[dict[str, Any]]:
        """Most recent top-ups and corrections for one user, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT delta_seconds, note, created_at
                FROM billing_ledger
                WHERE user_email = ? AND kind = 'grant'
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (self._normalize(email), int(limit)),
            ).fetchall()
        return [
            {"delta_seconds": int(r["delta_seconds"]), "note": str(r["note"]), "created_at": int(r["created_at"])}
            for r in rows
        ]

billing_service = BillingService()
