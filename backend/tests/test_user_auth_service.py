from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

import httpx

from main import create_app
from routers import auth as auth_router
from services.user_auth_service import (
    AUTH_FAILURE_LOCK_THRESHOLD,
    AUTH_IP_MAX_REQUESTS,
    AuthRateLimiter,
    AuthRateLimitError,
    UserAuthService,
    _b64encode,
)


def _run(coro):
    return asyncio.run(coro)


class AuthRateLimiterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limiter = AuthRateLimiter()

    def test_ip_window_rejects_after_budget(self) -> None:
        for _ in range(AUTH_IP_MAX_REQUESTS):
            self.limiter.hit_ip("10.0.0.1")
        with self.assertRaises(AuthRateLimitError) as ctx:
            self.limiter.hit_ip("10.0.0.1")
        self.assertGreater(ctx.exception.retry_after, 0)

    def test_ip_window_is_per_address(self) -> None:
        for _ in range(AUTH_IP_MAX_REQUESTS):
            self.limiter.hit_ip("10.0.0.1")
        # A different address still has its own budget.
        self.limiter.hit_ip("10.0.0.2")

    def test_ip_window_forgets_old_events(self) -> None:
        events = self.limiter._ip_events.setdefault("10.0.0.1", deque())
        stale = time.monotonic() - 3600
        for _ in range(AUTH_IP_MAX_REQUESTS):
            events.append(stale)
        # All events are outside the window, so the budget is free again.
        self.limiter.hit_ip("10.0.0.1")

    def test_lockout_after_repeated_failures(self) -> None:
        email = "user@example.com"
        for _ in range(AUTH_FAILURE_LOCK_THRESHOLD):
            self.limiter.record_login_failure(email)
        remaining = self.limiter.lockout_remaining(email)
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, 15 * 60)

    def test_lockout_clears_after_window(self) -> None:
        email = "user@example.com"
        failures = self.limiter._login_failures.setdefault(email.lower(), deque())
        stale = time.monotonic() - 3600
        for _ in range(AUTH_FAILURE_LOCK_THRESHOLD):
            failures.append(stale)
        self.assertEqual(self.limiter.lockout_remaining(email), 0)

    def test_successful_login_clears_failures(self) -> None:
        email = "user@example.com"
        self.limiter.record_login_failure(email)
        self.limiter.record_login_failure(email)
        self.limiter.clear_login_failures(email)
        self.assertEqual(self.limiter.lockout_remaining(email), 0)

    def test_lockout_key_is_email_case_insensitive(self) -> None:
        self.limiter.record_login_failure("User@Example.com")
        for _ in range(AUTH_FAILURE_LOCK_THRESHOLD - 1):
            self.limiter.record_login_failure("user@example.com")
        self.assertGreater(self.limiter.lockout_remaining("USER@example.com"), 0)


class UserAuthServiceSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.service = UserAuthService(db_path=Path(self._tmp.name) / "auth_test.db")
        self.user = self.service.register_user("owner@example.com", "password-1")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _legacy_token(self, email: str) -> str:
        payload = {"sub": email, "admin": False, "iat": int(time.time()), "exp": int(time.time()) + 3600}
        payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        return f"vsu.{_b64encode(payload_bytes)}.{self.service._sign(payload_bytes)}"

    def test_token_contains_jti_and_session_is_recorded(self) -> None:
        token = self.service.create_access_token(self.user, client_id="client-a")
        verified = self.service.verify_access_token(token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified["email"], "owner@example.com")
        self.assertTrue(verified.get("jti"))
        self.assertEqual(verified.get("client_id"), "client-a")

    def test_legacy_token_without_jti_is_rejected(self) -> None:
        legacy = self._legacy_token("owner@example.com")
        self.assertIsNone(self.service.verify_access_token(legacy))

    def test_revoked_session_invalidates_token(self) -> None:
        token = self.service.create_access_token(self.user)
        verified = self.service.verify_access_token(token)
        self.assertIsNotNone(verified)
        self.assertTrue(self.service.revoke_session(verified["jti"]))
        self.assertIsNone(self.service.verify_access_token(token))
        # Revoking again is a no-op.
        self.assertFalse(self.service.revoke_session(verified["jti"]))

    def test_revoke_other_sessions_keeps_current(self) -> None:
        current_token = self.service.create_access_token(self.user, client_id="this-device")
        other_token = self.service.create_access_token(self.user, client_id="other-device")
        current = self.service.verify_access_token(current_token)
        self.assertIsNotNone(current)
        revoked = self.service.revoke_other_sessions(
            self.user["email"], current_jti=current["jti"]
        )
        self.assertEqual(revoked, 1)
        self.assertIsNotNone(self.service.verify_access_token(current_token))
        self.assertIsNone(self.service.verify_access_token(other_token))

    def test_list_active_sessions_marks_current(self) -> None:
        current_token = self.service.create_access_token(self.user, client_id="this-device")
        self.service.create_access_token(self.user, client_id="other-device")
        current = self.service.verify_access_token(current_token)
        sessions = self.service.list_active_sessions(
            self.user["email"], current_jti=current["jti"]
        )
        self.assertEqual(len(sessions), 2)
        flagged = [s for s in sessions if s["is_current"]]
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0]["client_id"], "this-device")
        self.assertNotIn("jti", sessions[0])

    def test_change_password_rejects_wrong_current(self) -> None:
        with self.assertRaises(ValueError):
            self.service.change_password(
                self.user["email"], "wrong-current", "password-2"
            )
        # Old password still authenticates.
        self.assertIsNotNone(
            self.service.authenticate_user("owner@example.com", "password-1")
        )

    def test_change_password_rejects_short_new(self) -> None:
        with self.assertRaises(ValueError):
            self.service.change_password(
                self.user["email"], "password-1", "abc"
            )

    def test_change_password_rotates_hash_and_revokes_other_sessions(self) -> None:
        current_token = self.service.create_access_token(self.user, client_id="this-device")
        other_token = self.service.create_access_token(self.user, client_id="other-device")
        current = self.service.verify_access_token(current_token)

        updated = self.service.change_password(
            self.user["email"],
            "password-1",
            "password-2",
            current_jti=current["jti"],
        )
        self.assertEqual(updated["email"], self.user["email"])

        # Old password no longer works, new one does.
        self.assertIsNone(self.service.authenticate_user("owner@example.com", "password-1"))
        self.assertIsNotNone(self.service.authenticate_user("owner@example.com", "password-2"))

        # Current session survives, other devices were revoked.
        self.assertIsNotNone(self.service.verify_access_token(current_token))
        self.assertIsNone(self.service.verify_access_token(other_token))


class AuthApiEndpointTests(unittest.TestCase):
    """Smoke coverage for the /api/auth endpoints added with sessions."""

    def setUp(self) -> None:
        self._auth_env_patcher = patch.dict(
            os.environ,
            {
                "VOICESPIRIT_API_TOKEN": "test-api-token",
                "VOICESPIRIT_ADMIN_TOKEN": "test-admin-token",
            },
            clear=False,
        )
        self._auth_env_patcher.start()
        self._tmp = tempfile.TemporaryDirectory()
        self._service_patch = patch.object(
            auth_router, "user_auth_service", UserAuthService(db_path=Path(self._tmp.name) / "auth_api.db")
        )
        self._service_patch.start()
        self._limiter_patch = patch.object(auth_router, "auth_rate_limiter", AuthRateLimiter())
        self._limiter_patch.start()
        self.app = create_app()

    def tearDown(self) -> None:
        self._limiter_patch.stop()
        self._service_patch.stop()
        self._auth_env_patcher.stop()
        self._tmp.cleanup()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async def runner() -> httpx.Response:
            transport = httpx.ASGITransport(app=self.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return _run(runner())

    def _register_and_login(self, email: str = "api-user@example.com", password: str = "password-1") -> str:
        response = self._request(
            "POST",
            "/api/auth/register",
            json={"email": email, "password": password},
            headers={"X-Client-ID": "test-client"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["access_token"]

    def _auth_header(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_register_login_returns_session(self) -> None:
        token = self._register_and_login()
        me = self._request("GET", "/api/auth/me", headers=self._auth_header(token))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "api-user@example.com")

    def test_login_failure_then_success(self) -> None:
        self._register_and_login()
        bad = self._request(
            "POST",
            "/api/auth/login",
            json={"email": "api-user@example.com", "password": "nope-nope"},
        )
        self.assertEqual(bad.status_code, 401)
        self.assertEqual(bad.json()["detail"]["code"], "AUTH_LOGIN_FAILED")
        good = self._request(
            "POST",
            "/api/auth/login",
            json={"email": "api-user@example.com", "password": "password-1"},
            headers={"X-Client-ID": "test-client"},
        )
        self.assertEqual(good.status_code, 200)

    def test_change_password_flow(self) -> None:
        token = self._register_and_login()
        wrong = self._request(
            "POST",
            "/api/auth/change-password",
            json={"current_password": "wrong", "new_password": "password-2"},
            headers=self._auth_header(token),
        )
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(wrong.json()["detail"]["code"], "AUTH_CHANGE_PASSWORD_FAILED")

        ok = self._request(
            "POST",
            "/api/auth/change-password",
            json={"current_password": "password-1", "new_password": "password-2"},
            headers=self._auth_header(token),
        )
        self.assertEqual(ok.status_code, 200)
        relogin = self._request(
            "POST",
            "/api/auth/login",
            json={"email": "api-user@example.com", "password": "password-2"},
        )
        self.assertEqual(relogin.status_code, 200)

    def test_logout_revokes_session(self) -> None:
        token = self._register_and_login()
        logout = self._request("POST", "/api/auth/logout", headers=self._auth_header(token))
        self.assertEqual(logout.status_code, 200)
        self.assertTrue(logout.json()["ok"])
        me = self._request("GET", "/api/auth/me", headers=self._auth_header(token))
        self.assertEqual(me.status_code, 401)

    def test_sessions_listing_and_revoke_others(self) -> None:
        token_a = self._register_and_login()
        login_b = self._request(
            "POST",
            "/api/auth/login",
            json={"email": "api-user@example.com", "password": "password-1"},
            headers={"X-Client-ID": "device-b"},
        )
        self.assertEqual(login_b.status_code, 200)
        token_b = login_b.json()["access_token"]

        listing = self._request("GET", "/api/auth/sessions", headers=self._auth_header(token_a))
        self.assertEqual(listing.status_code, 200)
        sessions = listing.json()
        self.assertEqual(len(sessions), 2)
        current_flags = [s["is_current"] for s in sessions]
        self.assertEqual(current_flags.count(True), 1)

        revoke = self._request(
            "POST", "/api/auth/sessions/revoke-others", headers=self._auth_header(token_a)
        )
        self.assertEqual(revoke.status_code, 200)
        self.assertEqual(revoke.json()["revoked"], 1)

        me_a = self._request("GET", "/api/auth/me", headers=self._auth_header(token_a))
        self.assertEqual(me_a.status_code, 200)
        me_b = self._request("GET", "/api/auth/me", headers=self._auth_header(token_b))
        self.assertEqual(me_b.status_code, 401)

    def test_login_lockout_after_repeated_failures(self) -> None:
        self._register_and_login()
        for _ in range(AUTH_FAILURE_LOCK_THRESHOLD):
            failed = self._request(
                "POST",
                "/api/auth/login",
                json={"email": "api-user@example.com", "password": "nope-nope"},
            )
            self.assertEqual(failed.status_code, 401)
        locked = self._request(
            "POST",
            "/api/auth/login",
            json={"email": "api-user@example.com", "password": "password-1"},
        )
        self.assertEqual(locked.status_code, 429)
        detail = locked.json()["detail"]
        self.assertEqual(detail["code"], "AUTH_RATE_LIMITED")
        self.assertGreater(detail["meta"]["retry_after"], 0)
        self.assertTrue(locked.headers.get("Retry-After"))

    def test_register_ip_rate_limit(self) -> None:
        last_response = None
        for index in range(AUTH_IP_MAX_REQUESTS + 1):
            last_response = self._request(
                "POST",
                "/api/auth/register",
                json={"email": f"bulk-{index}@example.com", "password": "password-1"},
            )
        self.assertEqual(last_response.status_code, 429)
        self.assertEqual(last_response.json()["detail"]["code"], "AUTH_RATE_LIMITED")

    def test_missing_token_rejected_on_protected_auth_endpoints(self) -> None:
        response = self._request("GET", "/api/auth/sessions")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "AUTH_TOKEN_MISSING")


if __name__ == "__main__":
    unittest.main()
