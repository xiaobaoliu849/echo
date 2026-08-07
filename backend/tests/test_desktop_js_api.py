"""Tests for the pywebview JS bridge (run_web_desktop.py).

Desktop mode cannot rely on blob-anchor downloads, so subtitle/transcript
exports go through DesktopJsApi.save_text_file. These tests stub the native
window/dialog and verify payload validation plus UTF-8 file writes. The window
control bridge (minimize / maximize toggle) and its maximize state tracking are
covered here as well.
"""

from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from run_web_desktop import (  # noqa: E402
    DesktopController,
    DesktopJsApi,
    attach_window_state_tracking,
    default_window_state,
)


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


class _FakeEvent:
    """Minimal stand-in for pywebview's Event objects (supports += / fire)."""

    def __init__(self) -> None:
        self.handlers: list = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self

    def fire(self) -> None:
        for handler in list(self.handlers):
            handler()


class _FakeWindow:
    """Stands in for the pywebview window; records dialog and control calls."""

    def __init__(self, selected=None):
        self._selected = selected
        self.dialog_calls: list[dict] = []
        self.minimize_calls = 0
        self.maximize_calls = 0
        self.restore_calls = 0
        self.events = SimpleNamespace(
            maximized=_FakeEvent(),
            restored=_FakeEvent(),
        )

    def create_file_dialog(self, dialog_type, save_filename=None, file_types=None):
        self.dialog_calls.append(
            {
                "dialog_type": dialog_type,
                "save_filename": save_filename,
                "file_types": file_types,
            }
        )
        return self._selected

    def minimize(self):
        self.minimize_calls += 1

    def maximize(self):
        self.maximize_calls += 1

    def restore(self):
        self.restore_calls += 1


def _make_api(selected=None) -> tuple[DesktopJsApi, _FakeWindow, DesktopController]:
    window = _FakeWindow(selected)
    controller = DesktopController(default_window_state())
    controller.attach_window(window, SimpleNamespace(SAVE_DIALOG="SAVE_DIALOG"))
    return DesktopJsApi(controller), window, controller


class SaveTextFileTests(unittest.TestCase):
    def test_writes_utf8_content_to_selected_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "out.srt"
            api, window, _ = _make_api(selected=str(target))
            result = api.save_text_file(
                {"filename": "meeting.srt", "data_base64": _b64("1\n00:00:00,000 --> 00:00:01,000\n你好世界")}
            )
            self.assertTrue(result["ok"])
            self.assertFalse(result["cancelled"])
            self.assertEqual(result["path"], str(target))
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "1\n00:00:00,000 --> 00:00:01,000\n你好世界",
            )
            self.assertEqual(window.dialog_calls[0]["save_filename"], "meeting.srt")
            self.assertIn("SRT", window.dialog_calls[0]["file_types"][0])

    def test_cancelled_dialog_returns_cancelled(self) -> None:
        api, window, _ = _make_api(selected=None)
        result = api.save_text_file({"filename": "a.vtt", "data_base64": _b64("WEBVTT\n")})
        self.assertFalse(result["ok"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(len(window.dialog_calls), 1)

    def test_tuple_dialog_result_is_unwrapped(self) -> None:
        # Most pywebview backends return a tuple/list of selected paths.
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out.vtt"
            api, _, _ = _make_api(selected=(str(target),))
            result = api.save_text_file({"filename": "a.vtt", "data_base64": _b64("WEBVTT\n")})
            self.assertTrue(result["ok"])
            self.assertEqual(result["path"], str(target))
            self.assertEqual(target.read_text(encoding="utf-8"), "WEBVTT\n")

    def test_trailing_dot_filename_not_doubled(self) -> None:
        api, window, _ = _make_api(selected=None)
        api.save_text_file({"filename": "meeting.", "data_base64": _b64("hi")})
        suggested = window.dialog_calls[0]["save_filename"]
        self.assertNotIn("..", suggested)
        self.assertTrue(suggested.endswith(".txt"))

    def test_empty_data_rejected_before_dialog(self) -> None:
        api, window, _ = _make_api(selected="x.srt")
        result = api.save_text_file({"filename": "a.srt", "data_base64": ""})
        self.assertFalse(result["ok"])
        self.assertEqual(len(window.dialog_calls), 0)

    def test_invalid_base64_rejected(self) -> None:
        api, _, _ = _make_api(selected="x.srt")
        result = api.save_text_file({"filename": "a.srt", "data_base64": "!!!not-base64!!!"})
        self.assertFalse(result["ok"])
        self.assertFalse(result["cancelled"])

    def test_unknown_extension_falls_back_to_txt(self) -> None:
        api, window, _ = _make_api(selected=None)
        api.save_text_file({"filename": "notes.md", "data_base64": _b64("hi")})
        self.assertTrue(window.dialog_calls[0]["save_filename"].endswith(".txt"))

    def test_missing_extension_appended_to_suggested_name(self) -> None:
        api, window, _ = _make_api(selected=None)
        api.save_text_file({"filename": "meeting", "data_base64": _b64("hi")})
        self.assertTrue(window.dialog_calls[0]["save_filename"].endswith(".txt"))

    def test_window_not_ready(self) -> None:
        controller = DesktopController(default_window_state())
        api = DesktopJsApi(controller)
        result = api.save_text_file({"filename": "a.srt", "data_base64": _b64("hi")})
        self.assertFalse(result["ok"])
        self.assertIn("not ready", result["message"])

    def test_save_audio_file_still_uses_shared_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "voice.mp3"
            api, window, _ = _make_api(selected=str(target))
            result = api.save_audio_file(
                {"filename": "voice.mp3", "data_base64": _b64("fake-audio")}
            )
            self.assertTrue(result["ok"])
            self.assertEqual(target.read_bytes(), b"fake-audio")
            self.assertEqual(window.dialog_calls[0]["save_filename"], "voice.mp3")


class WindowControlTests(unittest.TestCase):
    def test_minimize_calls_native_minimize(self) -> None:
        api, window, _ = _make_api()
        result = api.minimize_window()
        self.assertTrue(result["ok"])
        self.assertEqual(window.minimize_calls, 1)

    def test_toggle_maximize_maximizes_then_restores(self) -> None:
        api, window, controller = _make_api()
        self.assertFalse(controller.is_window_maximized())

        first = api.toggle_maximize_window()
        self.assertTrue(first["ok"])
        self.assertTrue(first["maximized"])
        self.assertEqual(window.maximize_calls, 1)
        self.assertEqual(window.restore_calls, 0)

        second = api.toggle_maximize_window()
        self.assertTrue(second["ok"])
        self.assertFalse(second["maximized"])
        self.assertEqual(window.maximize_calls, 1)
        self.assertEqual(window.restore_calls, 1)

    def test_toggle_maximize_respects_external_maximize_event(self) -> None:
        # OS-level maximize (title-bar double-click, Win+Up) must not desync
        # the tracked state that drives the toggle decision.
        api, window, controller = _make_api()
        window.events.maximized.fire()
        self.assertTrue(controller.is_window_maximized())

        result = api.toggle_maximize_window()
        self.assertTrue(result["ok"])
        self.assertFalse(result["maximized"])
        self.assertEqual(window.restore_calls, 1)
        self.assertEqual(window.maximize_calls, 0)

    def test_toggle_maximize_respects_external_restore_event(self) -> None:
        api, window, controller = _make_api()
        self.assertTrue(api.toggle_maximize_window()["maximized"])

        window.events.restored.fire()
        self.assertFalse(controller.is_window_maximized())

        result = api.toggle_maximize_window()
        self.assertTrue(result["ok"])
        self.assertTrue(result["maximized"])
        self.assertEqual(window.restore_calls, 0)
        self.assertEqual(window.maximize_calls, 2)

    def test_controls_guard_against_missing_window(self) -> None:
        controller = DesktopController(default_window_state())
        api = DesktopJsApi(controller)
        self.assertFalse(api.minimize_window()["ok"])
        self.assertFalse(api.toggle_maximize_window()["ok"])

    def test_closed_state_tracking_uses_live_maximize_state(self) -> None:
        controller = DesktopController(default_window_state())
        window = _FakeWindow()
        window.events.closed = _FakeEvent()
        attach_window_state_tracking(window, controller.window_state, controller)
        api = DesktopJsApi(controller)
        controller.attach_window(window, SimpleNamespace(SAVE_DIALOG="SAVE_DIALOG"))

        api.toggle_maximize_window()
        window.events.closed.fire()

        self.assertTrue(controller.window_state["maximized"])


if __name__ == "__main__":
    unittest.main()
