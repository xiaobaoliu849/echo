"""Self-service sign-up and per-account preferences for hosted mode.

Sign-up needs the community invite code the operator posts in the
neighbourhood group (changeable from the admin console), so the free trial
minutes cannot be farmed by anyone who gets hold of the installer. Each new
account gets the trial package automatically.

Preferences (who is learning, English level, coach defaults, interface
language, onboarding done) live on the account, so they follow the user to
another computer.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any

from .config_loader import get_data_file_path
from .db_utils import get_db_connection

REGISTRATION_FILE = "hosted_registration.json"
TRIAL_MINUTES = 30
TRIAL_VALID_DAYS = 30
ACCOUNT_RE = re.compile(r"^[\w\-一-鿿]{2,30}$")

LEARNERS = ("child", "adult")
LEVELS = ("beginner", "intermediate", "advanced", "ielts")
UI_LANGUAGES = ("zh-CN", "en-US")
DEFAULT_PREFS: dict[str, Any] = {
    "learner": "adult",
    "level": "beginner",
    "native_language": "Chinese",
    "coach": True,
    "ui_language": "zh-CN",
    "onboarded": False,
    "signup": "admin",
}


# ── sign-up: single-use invite codes and trial limits ───────────────────
#
# Every invite code registers one account. The free trial is further limited
# to one per device and a few per network, so one person cannot farm trial
# minutes with fresh accounts.

TRIAL_PER_NETWORK = 3
TRIAL_NETWORK_WINDOW_DAYS = 30
INVITE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O or 1/I


def _registration_path() -> Path:
    return get_data_file_path(REGISTRATION_FILE)


def load_registration() -> dict[str, Any]:
    """Whether self-service sign-up is open (the invite codes live in the DB)."""
    try:
        data = json.loads(_registration_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"enabled": bool(data.get("enabled")) if isinstance(data, dict) else False}


def save_registration(*, enabled: bool) -> dict[str, Any]:
    value = {"enabled": bool(enabled)}
    target = _registration_path()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return value


def generate_invite_code() -> str:
    return "".join(secrets.choice(INVITE_ALPHABET) for _ in range(6))


class InviteStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or get_data_file_path("voice_spirit.db")
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS invite_codes (
                    code TEXT PRIMARY KEY,
                    note TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    used_by TEXT,
                    used_at INTEGER,
                    revoked INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS trial_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT NOT NULL,
                    device_id TEXT NOT NULL DEFAULT '',
                    network TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    def create(self, count: int, note: str = "") -> list[str]:
        codes: list[str] = []
        now = int(time.time())
        with get_db_connection(self.db_path) as conn:
            while len(codes) < count:
                code = generate_invite_code()
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO invite_codes (code, note, created_at) VALUES (?, ?, ?)",
                    (code, str(note or "").strip()[:60], now),
                )
                if cursor.rowcount:
                    codes.append(code)
            conn.commit()
        return codes

    def list(self) -> list[dict[str, Any]]:
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM invite_codes ORDER BY created_at DESC, code").fetchall()
        return [
            {
                "code": str(r["code"]),
                "note": str(r["note"]),
                "created_at": int(r["created_at"]),
                "used_by": r["used_by"],
                "used_at": int(r["used_at"]) if r["used_at"] else None,
                "revoked": bool(r["revoked"]),
            }
            for r in rows
        ]

    def revoke(self, code: str) -> bool:
        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE invite_codes SET revoked = 1 WHERE code = ? AND used_by IS NULL",
                (str(code or "").strip().upper(),),
            )
            conn.commit()
        return bool(cursor.rowcount)

    def claim(self, code: str, email: str) -> bool:
        """Atomically mark an unused code as used by ``email``; False if not usable."""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.execute(
                """
                UPDATE invite_codes SET used_by = ?, used_at = ?
                WHERE code = ? AND used_by IS NULL AND revoked = 0
                """,
                (email, int(time.time()), str(code or "").strip().upper()),
            )
            conn.commit()
        return bool(cursor.rowcount)

    def release(self, code: str, email: str) -> None:
        """Undo a claim when the account could not be created after all."""
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                "UPDATE invite_codes SET used_by = NULL, used_at = NULL WHERE code = ? AND used_by = ?",
                (str(code or "").strip().upper(), email),
            )
            conn.commit()

    def trial_allowed(self, *, device_id: str, network: str) -> bool:
        since = int(time.time()) - TRIAL_NETWORK_WINDOW_DAYS * 86400
        with get_db_connection(self.db_path) as conn:
            if device_id:
                row = conn.execute("SELECT 1 FROM trial_claims WHERE device_id = ? LIMIT 1", (device_id,)).fetchone()
                if row:
                    return False
            if network:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM trial_claims WHERE network = ? AND created_at >= ?",
                    (network, since),
                ).fetchone()
                if int(row["n"] or 0) >= TRIAL_PER_NETWORK:
                    return False
        return True

    def record_trial(self, email: str, *, device_id: str, network: str) -> None:
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO trial_claims (user_email, device_id, network, created_at) VALUES (?, ?, ?, ?)",
                (email, device_id, network, int(time.time())),
            )
            conn.commit()


def validate_account_name(account: str) -> str:
    """Return the cleaned short account name or raise ValueError."""
    cleaned = str(account or "").strip()
    if "@" in cleaned or not ACCOUNT_RE.match(cleaned):
        raise ValueError("账号用 2–30 个字（中文、字母、数字、- 或 _），例如 1203。")
    return cleaned


# ── preferences ──────────────────────────────────────────────────────────


class AccountPrefsStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or get_data_file_path("voice_spirit.db")
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS account_prefs (
                    user_email TEXT PRIMARY KEY,
                    prefs TEXT NOT NULL DEFAULT '{}',
                    updated_at INTEGER NOT NULL
                )
                """
            )
            conn.commit()

    @staticmethod
    def _normalize(email: str) -> str:
        return str(email or "").strip().lower()

    def get(self, email: str) -> dict[str, Any]:
        with get_db_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT prefs FROM account_prefs WHERE user_email = ?", (self._normalize(email),)
            ).fetchone()
        stored: dict[str, Any] = {}
        if row:
            try:
                loaded = json.loads(row["prefs"])
                stored = loaded if isinstance(loaded, dict) else {}
            except ValueError:
                stored = {}
        return {**DEFAULT_PREFS, **sanitize_prefs(stored, allow_signup=True)}

    def update(self, email: str, patch: dict[str, Any], *, allow_signup: bool = False) -> dict[str, Any]:
        merged = {**self.get(email), **sanitize_prefs(patch, allow_signup=allow_signup)}
        with get_db_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO account_prefs (user_email, prefs, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(user_email) DO UPDATE SET prefs = excluded.prefs, updated_at = excluded.updated_at
                """,
                (self._normalize(email), json.dumps(merged, ensure_ascii=False), int(time.time())),
            )
            conn.commit()
        return merged

    def signups(self) -> dict[str, str]:
        with get_db_connection(self.db_path) as conn:
            rows = conn.execute("SELECT user_email, prefs FROM account_prefs").fetchall()
        out: dict[str, str] = {}
        for row in rows:
            try:
                out[str(row["user_email"])] = str(json.loads(row["prefs"]).get("signup") or "admin")
            except (ValueError, AttributeError):
                continue
        return out


def sanitize_prefs(raw: dict[str, Any], *, allow_signup: bool = False) -> dict[str, Any]:
    """Keep only known keys with valid values; ``signup`` is server-set only."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    if raw.get("learner") in LEARNERS:
        out["learner"] = raw["learner"]
    if raw.get("level") in LEVELS:
        out["level"] = raw["level"]
    native = str(raw.get("native_language") or "").strip()
    if native and len(native) <= 40:
        out["native_language"] = native
    if isinstance(raw.get("coach"), bool):
        out["coach"] = raw["coach"]
    if raw.get("ui_language") in UI_LANGUAGES:
        out["ui_language"] = raw["ui_language"]
    if isinstance(raw.get("onboarded"), bool):
        out["onboarded"] = raw["onboarded"]
    if allow_signup and raw.get("signup") in ("self", "admin"):
        out["signup"] = raw["signup"]
    return out


account_prefs_store = AccountPrefsStore()
invite_store = InviteStore()
