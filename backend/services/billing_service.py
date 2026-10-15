"""Per-user realtime minutes balance for hosted mode.

Balances are kept in whole seconds. Every top-up is a *lot* in
``billing_lots`` with its own expiry; usage drains the lot that expires
first, and a lot that expires unused is written off. The balance is the
sum of unexpired lots (``billing_balances`` caches it for listings), and
every change is written to ``billing_ledger`` in the same transaction, so
it can always be reconciled against its history.
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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS billing_lots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT NOT NULL,
                    granted_seconds INTEGER NOT NULL,
                    remaining_seconds INTEGER NOT NULL,
                    expires_at INTEGER,
                    note TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_billing_lots_user ON billing_lots(user_email, remaining_seconds)"
            )
            # Balances from before lots existed become one lot that never
            # expires, so nobody loses minutes they already had.
            conn.execute(
                """
                INSERT INTO billing_lots (user_email, granted_seconds, remaining_seconds, expires_at, note, created_at)
                SELECT b.user_email, b.balance_seconds, b.balance_seconds, NULL, 'legacy', b.updated_at
                FROM billing_balances b
                WHERE b.balance_seconds > 0
                  AND NOT EXISTS (SELECT 1 FROM billing_lots l WHERE l.user_email = b.user_email)
                """
            )
            conn.commit()

    @staticmethod
    def _normalize(email: str) -> str:
        return str(email or "").strip().lower()

    @staticmethod
    def _unexpired_total(conn, user: str, now: int) -> int:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(remaining_seconds), 0) AS total
            FROM billing_lots
            WHERE user_email = ? AND remaining_seconds > 0 AND (expires_at IS NULL OR expires_at > ?)
            """,
            (user, now),
        ).fetchone()
        return int(row["total"] or 0)

    @staticmethod
    def _ledger(
        conn,
        user: str,
        kind: str,
        delta: int,
        now: int,
        *,
        wall: int = 0,
        provider: str = "",
        model: str = "",
        note: str = "",
    ) -> None:
        conn.execute(
            """
            INSERT INTO billing_ledger
                (user_email, kind, delta_seconds, wall_seconds, provider, model, note, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user, kind, int(delta), int(wall), provider, model, note, now),
        )

    @staticmethod
    def _store_balance(conn, user: str, balance: int, now: int) -> None:
        conn.execute(
            """
            INSERT INTO billing_balances (user_email, balance_seconds, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_email) DO UPDATE SET
                balance_seconds = excluded.balance_seconds,
                updated_at = excluded.updated_at
            """,
            (user, balance, now),
        )

    def _expire_locked(self, conn, user: str, now: int) -> None:
        """Write off lots that expired unused. Caller holds the write lock."""
        rows = conn.execute(
            """
            SELECT id, remaining_seconds FROM billing_lots
            WHERE user_email = ? AND remaining_seconds > 0 AND expires_at IS NOT NULL AND expires_at <= ?
            """,
            (user, now),
        ).fetchall()
        if not rows:
            return
        expired = sum(int(r["remaining_seconds"]) for r in rows)
        conn.executemany("UPDATE billing_lots SET remaining_seconds = 0 WHERE id = ?", [(r["id"],) for r in rows])
        self._ledger(conn, user, "expire", -expired, now, note=f"{len(rows)} 笔到期")
        self._store_balance(conn, user, self._unexpired_total(conn, user, now), now)

    def get_balance(self, email: str) -> int:
        with self._connect() as conn:
            return self._unexpired_total(conn, self._normalize(email), int(time.time()))

    def expire_due(self) -> None:
        """Write off every expired lot, so cached balances and the ledger agree."""
        now = int(time.time())
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            users = conn.execute(
                """
                SELECT DISTINCT user_email FROM billing_lots
                WHERE remaining_seconds > 0 AND expires_at IS NOT NULL AND expires_at <= ?
                """,
                (now,),
            ).fetchall()
            for row in users:
                self._expire_locked(conn, str(row["user_email"]), now)
            conn.commit()

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
        valid_days: int = 0,
    ) -> int:
        user = self._normalize(email)
        now = int(time.time())
        delta = int(delta_seconds)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._expire_locked(conn, user, now)
            current = self._unexpired_total(conn, user, now)
            if delta > 0:
                expires_at = now + int(valid_days) * 86400 if valid_days > 0 else None
                conn.execute(
                    """
                    INSERT INTO billing_lots
                        (user_email, granted_seconds, remaining_seconds, expires_at, note, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user, delta, delta, expires_at, note, now),
                )
            elif delta < 0:
                # Drain the lot that expires first; never-expiring lots last.
                # Usage never drives the balance negative; the meter hangs up
                # at 0, so any overshoot is at most one metering tick.
                need = -delta
                lots = conn.execute(
                    """
                    SELECT id, remaining_seconds FROM billing_lots
                    WHERE user_email = ? AND remaining_seconds > 0 AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY expires_at IS NULL, expires_at, id
                    """,
                    (user, now),
                ).fetchall()
                for lot in lots:
                    if need <= 0:
                        break
                    take = min(need, int(lot["remaining_seconds"]))
                    conn.execute(
                        "UPDATE billing_lots SET remaining_seconds = remaining_seconds - ? WHERE id = ?",
                        (take, lot["id"]),
                    )
                    need -= take
            new_balance = self._unexpired_total(conn, user, now)
            self._store_balance(conn, user, new_balance, now)
            self._ledger(
                conn,
                user,
                kind,
                new_balance - current,
                now,
                wall=wall_seconds,
                provider=provider,
                model=model,
                note=note,
            )
            conn.commit()
        return new_balance

    def grant(self, email: str, seconds: int, *, note: str = "", valid_days: int = 0) -> int:
        """Add (or, negative, deduct) minutes; new minutes expire after ``valid_days`` (0 = never)."""
        if int(seconds) == 0:
            raise ValueError("Grant amount must be non-zero.")
        return self._apply(email, int(seconds), kind="grant", note=note, valid_days=valid_days)

    def active_lots(self, email: str) -> list[dict[str, Any]]:
        """Unexpired minutes by lot, soonest expiry first (``expires_at`` None = never)."""
        now = int(time.time())
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT remaining_seconds, granted_seconds, expires_at, note, created_at
                FROM billing_lots
                WHERE user_email = ? AND remaining_seconds > 0 AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY expires_at IS NULL, expires_at, id
                """,
                (self._normalize(email), now),
            ).fetchall()
        return [
            {
                "remaining_seconds": int(r["remaining_seconds"]),
                "granted_seconds": int(r["granted_seconds"]),
                "expires_at": int(r["expires_at"]) if r["expires_at"] is not None else None,
                "note": str(r["note"]),
                "created_at": int(r["created_at"]),
            }
            for r in rows
        ]

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
        self.expire_due()
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
        """Most recent top-ups, corrections and expiries for one user, newest first."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT kind, delta_seconds, note, created_at
                FROM billing_ledger
                WHERE user_email = ? AND kind IN ('grant', 'expire') AND delta_seconds != 0
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (self._normalize(email), int(limit)),
            ).fetchall()
        return [
            {
                "kind": str(r["kind"]),
                "delta_seconds": int(r["delta_seconds"]),
                "note": str(r["note"]),
                "created_at": int(r["created_at"]),
            }
            for r in rows
        ]

    def recent_calls(self, email: str, *, since: int = 0, limit: int = 50, gap_seconds: int = 90) -> list[dict[str, Any]]:
        """Usage rows regrouped into calls, newest first.

        The ledger stores one row per metering tick (every 5-15 s), so a
        call is a run of same-model rows with no gap longer than
        ``gap_seconds`` between them.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT provider, model, delta_seconds, wall_seconds, created_at
                FROM billing_ledger
                WHERE user_email = ? AND kind = 'usage' AND created_at >= ?
                ORDER BY created_at, id
                """,
                (self._normalize(email), int(since)),
            ).fetchall()
        calls: list[dict[str, Any]] = []
        for r in rows:
            at = int(r["created_at"])
            wall = int(r["wall_seconds"] or 0)
            last = calls[-1] if calls else None
            if (
                last is not None
                and last["model"] == str(r["model"])
                and last["provider"] == str(r["provider"])
                and at - last["ended_at"] <= gap_seconds
            ):
                last["ended_at"] = at
                last["wall_seconds"] += wall
                last["billed_seconds"] -= int(r["delta_seconds"])
                continue
            calls.append(
                {
                    "provider": str(r["provider"]),
                    "model": str(r["model"]),
                    "started_at": at - wall,
                    "ended_at": at,
                    "wall_seconds": wall,
                    "billed_seconds": -int(r["delta_seconds"]),
                }
            )
        calls.reverse()
        return calls[: int(limit)]

billing_service = BillingService()
