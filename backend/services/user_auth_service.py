from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import time
from collections import deque
from pathlib import Path
from typing import Any

from .config_loader import BackendConfig

PBKDF2_ITERATIONS = 240_000
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
AUTH_WINDOW_SECONDS = 15 * 60
AUTH_IP_MAX_REQUESTS = 20
AUTH_FAILURE_LOCK_THRESHOLD = 5
AUTH_LOCKOUT_SECONDS = 15 * 60
REVOKED_SESSION_RETENTION_SECONDS = 60 * 60 * 24 * 7


class AuthRateLimitError(Exception):
    """Raised when an auth endpoint exceeds its rate limit or is locked out."""

    def __init__(self, retry_after: int, message: str = "Too many attempts. Try again later.") -> None:
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class AuthRateLimiter:
    """In-memory sliding-window limiter plus failed-login lockout.

    Deliberately process-local: the deployment model is a single uvicorn
    worker, so a shared external store (Redis) would add an operational
    dependency without protecting anything extra.
    """

    def __init__(self) -> None:
        self._ip_events: dict[str, deque[float]] = {}
        self._login_failures: dict[str, deque[float]] = {}

    @staticmethod
    def _prune(events: deque[float], now: float, window: float) -> None:
        cutoff = now - window
        while events and events[0] <= cutoff:
            events.popleft()

    def hit_ip(self, ip: str) -> None:
        """Record one auth request for ``ip`` and raise when over budget."""
        key = str(ip or "unknown")
        now = time.monotonic()
        events = self._ip_events.setdefault(key, deque())
        self._prune(events, now, AUTH_WINDOW_SECONDS)
        if len(events) >= AUTH_IP_MAX_REQUESTS:
            oldest = events[0] if events else now
            raise AuthRateLimitError(
                retry_after=math.ceil(AUTH_WINDOW_SECONDS - (now - oldest)),
                message="Too many authentication attempts from this address.",
            )
        events.append(now)

    def lockout_remaining(self, email: str) -> int:
        """Seconds left in the failed-login lockout for ``email`` (0 = clear)."""
        key = self._normalize(email)
        events = self._login_failures.get(key)
        if not events:
            return 0
        now = time.monotonic()
        self._prune(events, now, AUTH_LOCKOUT_SECONDS)
        if len(events) < AUTH_FAILURE_LOCK_THRESHOLD:
            return 0
        newest = events[-1]
        return math.ceil(AUTH_LOCKOUT_SECONDS - (now - newest))

    def record_login_failure(self, email: str) -> None:
        key = self._normalize(email)
        events = self._login_failures.setdefault(key, deque())
        events.append(time.monotonic())

    def clear_login_failures(self, email: str) -> None:
        self._login_failures.pop(self._normalize(email), None)

    @staticmethod
    def _normalize(email: str) -> str:
        return str(email or "").strip().lower()


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            return super().__exit__(exc_type, exc, traceback)
        finally:
            self.close()


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


class UserAuthService:
    def __init__(
        self,
        db_path: Path | None = None,
        config: BackendConfig | None = None,
    ) -> None:
        self.db_path = db_path or self._default_db_path()
        self.config = config or BackendConfig()
        self._has_users_cache: bool | None = None
        self._has_users_cached_at: float = 0.0
        self._init_db()

    @staticmethod
    def _default_db_path() -> Path:
        from .config_loader import get_data_file_path

        return get_data_file_path("voice_spirit.db")

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            factory=ClosingConnection,
        )
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    jti TEXT PRIMARY KEY,
                    user_email TEXT NOT NULL,
                    client_id TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    revoked_at INTEGER
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_email ON auth_sessions(user_email)"
            )
            conn.commit()

    def _normalize_email(self, email: str) -> str:
        return str(email or "").strip().lower()

    def _hash_password(self, password: str, salt_hex: str | None = None) -> tuple[str, str]:
        salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            str(password).encode("utf-8"),
            salt,
            PBKDF2_ITERATIONS,
        )
        return salt.hex(), digest.hex()

    def _verify_password(self, password: str, *, salt_hex: str, digest_hex: str) -> bool:
        _, candidate = self._hash_password(password, salt_hex=salt_hex)
        return hmac.compare_digest(candidate, digest_hex)

    def _get_secret(self) -> str:
        env_secret = os.getenv("VOICESPIRIT_JWT_SECRET", "").strip()
        if env_secret:
            return env_secret

        self.config.reload()
        data = self.config.get_all()
        auth_settings = data.get("auth_settings", {})
        if isinstance(auth_settings, dict):
            secret = str(auth_settings.get("user_auth_secret", "")).strip()
            if secret:
                return secret

        secret = secrets.token_urlsafe(48)
        patch = {"auth_settings": {"user_auth_secret": secret}}
        self.config.update(patch, merge=True)
        return secret

    def _sign(self, payload: bytes) -> str:
        secret = self._get_secret().encode("utf-8")
        signature = hmac.new(secret, payload, hashlib.sha256).digest()
        return _b64encode(signature)

    def _row_to_user(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        created_at = int(row["created_at"])
        return {
            "id": str(row["id"]),
            "email": str(row["email"]),
            "is_admin": bool(row["is_admin"]),
            "is_active": bool(row["is_active"]),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(created_at)),
        }

    _HAS_USERS_CACHE_TTL = 5.0

    def has_users(self) -> bool:
        # 鉴权中间件每个请求都会调用它，加一个短 TTL 缓存，避免每次都重连 SQLite 查询。
        # 注册新用户时会主动失效缓存（见 register_user），保证首个用户创建后立即生效。
        now = time.monotonic()
        if (
            self._has_users_cache is not None
            and now - self._has_users_cached_at < self._HAS_USERS_CACHE_TTL
        ):
            return self._has_users_cache
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM auth_users LIMIT 1").fetchone()
        result = row is not None
        self._has_users_cache = result
        self._has_users_cached_at = now
        return result

    def register_user(self, email: str, password: str) -> dict[str, Any]:
        normalized_email = self._normalize_email(email)
        password_text = str(password or "")
        if "@" not in normalized_email:
            raise ValueError("Email is invalid.")
        if len(password_text) < 6:
            raise ValueError("Password must contain at least 6 characters.")

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM auth_users WHERE email = ?",
                (normalized_email,),
            ).fetchone()
            if existing is not None:
                raise ValueError("Email is already registered.")

            count_row = conn.execute("SELECT COUNT(*) AS count FROM auth_users").fetchone()
            is_admin = int((count_row["count"] if count_row else 0) == 0)
            salt_hex, digest_hex = self._hash_password(password_text)
            created_at = int(time.time())
            cursor = conn.execute(
                """
                INSERT INTO auth_users (email, password_hash, password_salt, is_admin, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (normalized_email, digest_hex, salt_hex, is_admin, created_at),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM auth_users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        user = self._row_to_user(row)
        if user is None:
            raise RuntimeError("Failed to load registered user.")
        # 新用户创建成功，立即让 has_users 缓存失效，下一次调用会重新查询。
        self._has_users_cache = None
        return user

    def authenticate_user(self, email: str, password: str) -> dict[str, Any] | None:
        normalized_email = self._normalize_email(email)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM auth_users WHERE email = ?",
                (normalized_email,),
            ).fetchone()
        if row is None or not bool(row["is_active"]):
            return None
        if not self._verify_password(
            str(password or ""),
            salt_hex=str(row["password_salt"]),
            digest_hex=str(row["password_hash"]),
        ):
            return None
        return self._row_to_user(row)

    def create_access_token(
        self,
        user: dict[str, Any],
        *,
        expires_in: int = TOKEN_TTL_SECONDS,
        client_id: str = "",
    ) -> str:
        now = int(time.time())
        expires_at = now + max(60, int(expires_in))
        jti = secrets.token_urlsafe(24)
        payload = {
            "sub": str(user.get("email", "")).strip().lower(),
            "admin": bool(user.get("is_admin")),
            "iat": now,
            "exp": expires_at,
            "jti": jti,
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        encoded_payload = _b64encode(payload_bytes)
        signature = self._sign(payload_bytes)
        with self._connect() as conn:
            # Lazy housekeeping: drop sessions the verifier would reject anyway.
            conn.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= ?",
                (now - REVOKED_SESSION_RETENTION_SECONDS,),
            )
            conn.execute(
                """
                INSERT INTO auth_sessions (jti, user_email, client_id, created_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (
                    jti,
                    str(user.get("email", "")).strip().lower(),
                    str(client_id or "").strip()[:128],
                    now,
                    expires_at,
                ),
            )
            conn.commit()
        return f"vsu.{encoded_payload}.{signature}"

    def verify_access_token(self, token: str) -> dict[str, Any] | None:
        value = str(token or "").strip()
        parts = value.split(".")
        if len(parts) != 3 or parts[0] != "vsu":
            return None

        try:
            payload_bytes = _b64decode(parts[1])
            expected_signature = self._sign(payload_bytes)
            if not hmac.compare_digest(parts[2], expected_signature):
                return None
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None
        email = self._normalize_email(str(payload.get("sub", "")))
        expires_at = int(payload.get("exp", 0) or 0)
        jti = str(payload.get("jti", "")).strip()
        now = int(time.time())
        if not email or expires_at <= now:
            return None
        # Tokens issued before server-side sessions existed carry no jti;
        # reject them so "revoke all sessions" has complete coverage.
        if not jti:
            return None

        with self._connect() as conn:
            session = conn.execute(
                "SELECT client_id, expires_at, revoked_at FROM auth_sessions WHERE jti = ?",
                (jti,),
            ).fetchone()
            if session is None:
                return None
            if session["revoked_at"] is not None or int(session["expires_at"]) <= now:
                return None
            row = conn.execute(
                "SELECT * FROM auth_users WHERE email = ?",
                (email,),
            ).fetchone()
        user = self._row_to_user(row)
        if user is None or not bool(user.get("is_active")):
            return None
        user["jti"] = jti
        user["client_id"] = str(session["client_id"] or "")
        return user

    def revoke_session(self, jti: str) -> bool:
        cleaned = str(jti or "").strip()
        if not cleaned:
            return False
        now = int(time.time())
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE auth_sessions SET revoked_at = ? WHERE jti = ? AND revoked_at IS NULL",
                (now, cleaned),
            )
            conn.commit()
        return cursor.rowcount > 0

    def revoke_other_sessions(self, email: str, *, current_jti: str = "") -> int:
        normalized = self._normalize_email(email)
        now = int(time.time())
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE auth_sessions
                SET revoked_at = ?
                WHERE user_email = ? AND revoked_at IS NULL AND jti != ?
                """,
                (now, normalized, str(current_jti or "").strip()),
            )
            conn.commit()
        return cursor.rowcount

    def list_active_sessions(self, email: str, *, current_jti: str = "") -> list[dict[str, Any]]:
        normalized = self._normalize_email(email)
        now = int(time.time())
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT jti, client_id, created_at, expires_at
                FROM auth_sessions
                WHERE user_email = ? AND revoked_at IS NULL AND expires_at > ?
                ORDER BY created_at DESC
                """,
                (normalized, now),
            ).fetchall()
        current = str(current_jti or "").strip()
        return [
            {
                "client_id": str(row["client_id"] or ""),
                "created_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(row["created_at"]))
                ),
                "expires_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(int(row["expires_at"]))
                ),
                "is_current": bool(current) and str(row["jti"]) == current,
            }
            for row in rows
        ]

    def change_password(
        self,
        email: str,
        current_password: str,
        new_password: str,
        *,
        current_jti: str = "",
    ) -> dict[str, Any]:
        normalized = self._normalize_email(email)
        new_password_text = str(new_password or "")
        if len(new_password_text) < 6:
            raise ValueError("Password must contain at least 6 characters.")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM auth_users WHERE email = ?",
                (normalized,),
            ).fetchone()
        if row is None or not self._verify_password(
            str(current_password or ""),
            salt_hex=str(row["password_salt"]),
            digest_hex=str(row["password_hash"]),
        ):
            raise ValueError("Current password is incorrect.")
        salt_hex, digest_hex = self._hash_password(new_password_text)
        with self._connect() as conn:
            conn.execute(
                "UPDATE auth_users SET password_hash = ?, password_salt = ? WHERE id = ?",
                (digest_hex, salt_hex, row["id"]),
            )
            conn.commit()
            updated = conn.execute(
                "SELECT * FROM auth_users WHERE id = ?",
                (row["id"],),
            ).fetchone()
        self.revoke_other_sessions(normalized, current_jti=current_jti)
        user = self._row_to_user(updated)
        if user is None:
            raise RuntimeError("Failed to reload user after password change.")
        return user


user_auth_service = UserAuthService()
auth_rate_limiter = AuthRateLimiter()
