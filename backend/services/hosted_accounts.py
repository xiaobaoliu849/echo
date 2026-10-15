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


# ── invite code ──────────────────────────────────────────────────────────


def _registration_path() -> Path:
    return get_data_file_path(REGISTRATION_FILE)


def load_registration() -> dict[str, Any]:
    try:
        data = json.loads(_registration_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {"enabled": bool(data.get("enabled")), "code": str(data.get("code") or "")}


def save_registration(*, enabled: bool, code: str) -> dict[str, Any]:
    code = str(code or "").strip()
    if enabled and not 4 <= len(code) <= 32:
        raise ValueError("邀请码需要 4–32 个字符。")
    value = {"enabled": bool(enabled), "code": code}
    target = _registration_path()
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, target)
    return value


def generate_invite_code() -> str:
    # Easy to read aloud and type on a phone: no 0/O or 1/I.
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    return "".join(secrets.choice(alphabet) for _ in range(6))


def check_invite_code(code: str) -> bool:
    settings = load_registration()
    if not settings["enabled"] or not settings["code"]:
        return False
    return secrets.compare_digest(str(code or "").strip().upper(), settings["code"].upper())


def validate_account_name(account: str) -> str:
    """Return the cleaned short account name or raise ValueError."""
    cleaned = str(account or "").strip()
    if "@" in cleaned or not ACCOUNT_RE.match(cleaned):
        raise ValueError("账号用 2–30 个字（中文、字母、数字、- 或 _），例如门牌号 1203。")
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
