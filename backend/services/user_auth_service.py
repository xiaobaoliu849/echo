from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

from .config_loader import BackendConfig

PBKDF2_ITERATIONS = 240_000
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30


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

    def has_users(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM auth_users LIMIT 1").fetchone()
        return row is not None

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

    def create_access_token(self, user: dict[str, Any], *, expires_in: int = TOKEN_TTL_SECONDS) -> str:
        now = int(time.time())
        payload = {
            "sub": str(user.get("email", "")).strip().lower(),
            "admin": bool(user.get("is_admin")),
            "iat": now,
            "exp": now + max(60, int(expires_in)),
        }
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        encoded_payload = _b64encode(payload_bytes)
        signature = self._sign(payload_bytes)
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
        if not email or expires_at <= int(time.time()):
            return None

        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM auth_users WHERE email = ?",
                (email,),
            ).fetchone()
        user = self._row_to_user(row)
        if user is None or not bool(user.get("is_active")):
            return None
        return user


user_auth_service = UserAuthService()
