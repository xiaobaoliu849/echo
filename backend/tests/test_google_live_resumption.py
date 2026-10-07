"""Gemini Live GoAway handling: reconnect with the resumption handle."""
import unittest
from types import SimpleNamespace

from google.genai import errors

from services.google_live_resumption import ResumableGoogleLiveSession, is_google_live_connection_end
from services.realtime_voice_service import RealtimeVoiceService


def _update(handle, resumable=True):
    return SimpleNamespace(session_resumption_update=SimpleNamespace(new_handle=handle, resumable=resumable), go_away=None)


def _go_away():
    return SimpleNamespace(session_resumption_update=None, go_away=SimpleNamespace(time_left="10s"))


def _msg(name):
    return SimpleNamespace(session_resumption_update=None, go_away=None, name=name)


class _FakeLive:
    def __init__(self, messages, *, fail_with=None):
        self.messages = list(messages)
        self.fail_with = fail_with
        self.sent = []
        self.closed = False

    async def receive(self):
        for message in self.messages:
            yield message
        if self.fail_with is not None:
            raise self.fail_with

    async def send_realtime_input(self, **kwargs):
        if self.closed or self.fail_with is not None and not self.messages:
            raise errors.APIError(1000, "GoAway deadline exceeded", None)
        self.sent.append(kwargs)

    async def close(self):
        self.closed = True


class _FakeConnect:
    def __init__(self, sessions):
        self.sessions = list(sessions)
        self.handles = []

    def __call__(self, handle):
        self.handles.append(handle)
        session = self.sessions.pop(0)
        outer = self

        class _Cm:
            async def __aenter__(self):
                return session

            async def __aexit__(self, *exc):
                session.closed = True

        outer.last = session
        return _Cm()


class GoogleLiveResumptionTests(unittest.IsolatedAsyncioTestCase):
    async def test_go_away_reconnects_at_resumable_point_with_latest_handle(self):
        first = _FakeLive([_update("h1"), _msg("a"), _update("h2"), _go_away(), _msg("never")])
        second = _FakeLive([_msg("b")])
        connect = _FakeConnect([first, second])
        async with ResumableGoogleLiveSession(connect) as session:
            seen = [getattr(m, "name", None) async for m in session.receive()]
            self.assertTrue(first.closed)
            seen += [getattr(m, "name", None) async for m in session.receive()]
        self.assertEqual(connect.handles, [None, "h2"])
        self.assertEqual([n for n in seen if n], ["a", "b"])

    async def test_server_close_after_go_away_reconnects_instead_of_failing(self):
        closed = errors.APIError(1000, "GoAway deadline exceeded", None)
        first = _FakeLive([_update("h1"), _update(None, resumable=False), _go_away()], fail_with=closed)
        second = _FakeLive([_msg("b")])
        connect = _FakeConnect([first, second])
        async with ResumableGoogleLiveSession(connect) as session:
            _ = [m async for m in session.receive()]
            seen = [getattr(m, "name", None) async for m in session.receive()]
        self.assertEqual(connect.handles, [None, "h1"])
        self.assertEqual(seen, ["b"])

    async def test_send_after_close_retries_on_resumed_connection(self):
        first = _FakeLive([_update("h1")])
        second = _FakeLive([])
        connect = _FakeConnect([first, second])
        async with ResumableGoogleLiveSession(connect) as session:
            _ = [m async for m in session.receive()]
            first.closed = True
            await session.send_realtime_input(audio=b"x")
        self.assertEqual(second.sent, [{"audio": b"x"}])

    async def test_close_without_handle_or_policy_error_propagates(self):
        closed = errors.APIError(1000, "GoAway deadline exceeded", None)
        connect = _FakeConnect([_FakeLive([], fail_with=closed)])
        async with ResumableGoogleLiveSession(connect) as session:
            with self.assertRaises(errors.APIError):
                _ = [m async for m in session.receive()]

        policy = errors.ClientError(1008, "Publisher model not found", None)
        connect = _FakeConnect([_FakeLive([_update("h1")], fail_with=policy)])
        async with ResumableGoogleLiveSession(connect) as session:
            with self.assertRaises(errors.ClientError):
                _ = [m async for m in session.receive()]
        self.assertEqual(connect.handles, [None])

    async def test_failed_proactive_resume_keeps_old_connection(self):
        first = _FakeLive([_update("h1"), _go_away(), _msg("tail")])

        def connect(handle):
            if handle is not None:
                raise errors.ClientError(1011, "unavailable", None)
            return _FakeConnect([first])(handle)

        async with ResumableGoogleLiveSession(connect) as session:
            seen = [getattr(m, "name", None) async for m in session.receive()]
            self.assertFalse(first.closed)
        self.assertIn("tail", seen)

    async def test_stale_handle_is_not_a_resume_point(self):
        first = _FakeLive([_update("h1"), _update(None, resumable=True), _go_away(), _msg("tail")])
        connect = _FakeConnect([first])
        async with ResumableGoogleLiveSession(connect) as session:
            seen = [getattr(m, "name", None) async for m in session.receive()]
        self.assertEqual(connect.handles, [None])
        self.assertIn("tail", seen)

    async def test_setup_rejecting_resumption_falls_back_to_plain_session(self):
        plain = _FakeLive([_msg("ok")])

        def connect(handle):
            raise errors.ClientError(1007, "Invalid JSON payload: unknown field session_resumption", None)

        fallback = _FakeConnect([plain])
        async with ResumableGoogleLiveSession(connect, lambda: fallback(None)) as session:
            seen = [getattr(m, "name", None) async for m in session.receive()]
        self.assertEqual(seen, ["ok"])

    def test_connection_end_detection(self):
        self.assertTrue(is_google_live_connection_end(
            RuntimeError("received 1000 (OK) GoAway deadline exceeded; then sent 1000 (OK) GoAway deadline exceeded")
        ))
        self.assertFalse(is_google_live_connection_end(errors.ClientError(1008, "policy", None)))

    def test_chat_config_requests_resumption_and_sliding_window(self):
        config = RealtimeVoiceService._build_live_config(model="gemini-3.8-live")
        self.assertIsNotNone(config.session_resumption)
        self.assertIsNotNone(config.context_window_compression.sliding_window)
        avatar = RealtimeVoiceService._build_live_config(model="gemini-3.8-live", avatar_name="Ben")
        self.assertIsNone(avatar.session_resumption)


if __name__ == "__main__":
    unittest.main()
