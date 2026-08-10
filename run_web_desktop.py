#!/usr/bin/env python3
"""Launch VoiceSpirit Web inside a native desktop window (PyWebView)."""

from __future__ import annotations

import argparse
import atexit
import base64
import binascii
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Optional

APP_NAME = "VoiceSpirit"
PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIST_INDEX = PROJECT_ROOT / "frontend" / "dist" / "index.html"
HEALTH_URL = "http://127.0.0.1:8000/health"
APP_URL = "http://127.0.0.1:8000/app/"
DEFAULT_WINDOW_WIDTH = 1200
DEFAULT_WINDOW_HEIGHT = 800
MIN_WINDOW_WIDTH = 920
MIN_WINDOW_HEIGHT = 620
LOCAL_DESKTOP_LIB_DIR = PROJECT_ROOT / ".desktop-libs" / "usr" / "lib" / "x86_64-linux-gnu"
DESKTOP_FONTCONFIG_PATH = PROJECT_ROOT / "desktop_fonts.conf"
QT_RUNTIME_READY_ENV = "VOICE_SPIRIT_DESKTOP_QT_RUNTIME_READY"
WEBVIEW2_MEDIA_ARGS = "--use-fake-ui-for-media-stream --enable-media-stream"


def is_wsl_environment() -> bool:
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def build_app_url() -> str:
    cache_key = str(int(time.time()))
    try:
        stat = FRONTEND_DIST_INDEX.stat()
        cache_source = f"{stat.st_mtime_ns}:{stat.st_size}"
        cache_key = hashlib.sha1(cache_source.encode("utf-8")).hexdigest()[:12]
    except OSError:
        pass
    separator = "&" if "?" in APP_URL else "?"
    return f"{APP_URL}{separator}v={cache_key}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch VoiceSpirit desktop.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run desktop preflight checks without opening the GUI window.",
    )
    parser.add_argument(
        "--clear-webview",
        action="store_true",
        help="Clear persisted desktop WebView storage and exit.",
    )
    parser.add_argument(
        "--reset-cache",
        action="store_true",
        help="Clear persisted desktop WebView storage and continue launch.",
    )
    parser.add_argument(
        "--export-diagnostics",
        action="store_true",
        help="Export desktop runtime diagnostics as JSON and exit.",
    )
    return parser.parse_args()


def get_runtime_dir() -> Path:
    if sys.platform == "win32":
        base_dir = Path(os.environ.get("APPDATA", str(PROJECT_ROOT)))
        preferred_dir = base_dir / APP_NAME
        fallback_dir = PROJECT_ROOT / ".voicespirit-desktop"
    elif sys.platform == "darwin":
        base_dir = Path.home() / "Library" / "Application Support"
        preferred_dir = base_dir / APP_NAME
        fallback_dir = PROJECT_ROOT / ".voicespirit-desktop"
    else:
        if is_wsl_environment():
            local_state_home = PROJECT_ROOT / ".voicespirit-state"
            preferred_dir = local_state_home / APP_NAME
            fallback_dir = PROJECT_ROOT / ".voicespirit-desktop"
        else:
            xdg_state_home = os.environ.get("XDG_STATE_HOME")
            base_dir = Path(xdg_state_home) if xdg_state_home else Path.home() / ".local" / "state"
            preferred_dir = base_dir / APP_NAME
            fallback_dir = PROJECT_ROOT / ".voicespirit-desktop"

    for candidate in (preferred_dir, fallback_dir):
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError:
            continue

    raise RuntimeError("Unable to create a writable runtime directory for VoiceSpirit Desktop.")


RUNTIME_DIR = get_runtime_dir()
WINDOW_STATE_PATH = RUNTIME_DIR / "desktop_window.json"
WEBVIEW_STORAGE_DIR = RUNTIME_DIR / "webview"
DIAGNOSTICS_DIR = RUNTIME_DIR / "diagnostics"
LOCK_PATH = RUNTIME_DIR / "desktop.lock"
LATEST_ERROR_PATH = DIAGNOSTICS_DIR / "desktop_launch_error_latest.json"
LATEST_PREFLIGHT_PATH = DIAGNOSTICS_DIR / "desktop_preflight_latest.json"


class SingleInstanceLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._handle = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("a+", encoding="utf-8")
        self._handle.seek(0)

        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.release()
            raise RuntimeError(f"{APP_NAME} Desktop is already running.") from exc

        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(str(os.getpid()))
        self._handle.flush()

    def release(self) -> None:
        if self._handle is None:
            return

        try:
            self._handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self._handle.close()
            self._handle = None


def default_window_state() -> dict[str, Any]:
    return {
        "width": DEFAULT_WINDOW_WIDTH,
        "height": DEFAULT_WINDOW_HEIGHT,
        "x": None,
        "y": None,
        "maximized": False,
    }


def load_window_state() -> dict[str, Any]:
    state = default_window_state()
    if not WINDOW_STATE_PATH.is_file():
        return state

    try:
        raw_state = json.loads(WINDOW_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return state

    if not isinstance(raw_state, dict):
        return state

    if isinstance(raw_state.get("width"), int) and raw_state["width"] >= MIN_WINDOW_WIDTH:
        state["width"] = raw_state["width"]
    if isinstance(raw_state.get("height"), int) and raw_state["height"] >= MIN_WINDOW_HEIGHT:
        state["height"] = raw_state["height"]
    if isinstance(raw_state.get("x"), int):
        state["x"] = raw_state["x"]
    if isinstance(raw_state.get("y"), int):
        state["y"] = raw_state["y"]
    if isinstance(raw_state.get("maximized"), bool):
        state["maximized"] = raw_state["maximized"]

    return state


def normalize_window_state_for_launch(window_state: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(window_state)
    normalized["width"] = max(int(normalized["width"]), MIN_WINDOW_WIDTH)
    normalized["height"] = max(int(normalized["height"]), MIN_WINDOW_HEIGHT)

    if normalized["width"] > DEFAULT_WINDOW_WIDTH:
        normalized["width"] = DEFAULT_WINDOW_WIDTH
    if normalized["height"] > DEFAULT_WINDOW_HEIGHT:
        normalized["height"] = DEFAULT_WINDOW_HEIGHT

    # Always launch in normal restored (non-maximized) window mode
    normalized["maximized"] = False

    return normalized


def save_window_state(state: dict[str, Any]) -> None:
    WINDOW_STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )


def clear_webview_storage() -> bool:
    if not WEBVIEW_STORAGE_DIR.exists():
        return False
    shutil.rmtree(WEBVIEW_STORAGE_DIR, ignore_errors=True)
    return True


def fetch_json(url: str, timeout: float = 1.5) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if not (200 <= int(resp.status) < 400):
                return None
            payload = json.loads(resp.read().decode("utf-8"))
            if isinstance(payload, dict):
                return payload
    except Exception:
        return None
    return None


def collect_desktop_diagnostics() -> dict[str, Any]:
    frontend_exists = FRONTEND_DIST_INDEX.is_file()
    frontend_assets_dir = FRONTEND_DIST_INDEX.parent / "assets"
    frontend_assets = []
    if frontend_assets_dir.is_dir():
        frontend_assets = sorted(path.name for path in frontend_assets_dir.iterdir() if path.is_file())

    diagnostics: dict[str, Any] = {
        "app_name": APP_NAME,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "python": sys.version,
            "executable": sys.executable,
            "is_wsl": is_wsl_environment(),
        },
        "paths": {
            "project_root": str(PROJECT_ROOT),
            "runtime_dir": str(RUNTIME_DIR),
            "window_state_path": str(WINDOW_STATE_PATH),
            "webview_storage_dir": str(WEBVIEW_STORAGE_DIR),
            "diagnostics_dir": str(DIAGNOSTICS_DIR),
            "frontend_dist_index": str(FRONTEND_DIST_INDEX),
        },
        "frontend": {
            "dist_exists": frontend_exists,
            "dist_mtime_ns": FRONTEND_DIST_INDEX.stat().st_mtime_ns if frontend_exists else None,
            "dist_size": FRONTEND_DIST_INDEX.stat().st_size if frontend_exists else None,
            "assets": frontend_assets,
        },
        "desktop_runtime": {
            "app_url": APP_URL,
            "cache_busted_url": build_app_url(),
            "health_url": HEALTH_URL,
            "pywebview_installed": find_spec("webview") is not None,
            "window_state": load_window_state(),
            "webview_storage_exists": WEBVIEW_STORAGE_DIR.exists(),
            "webview_storage_entries": sorted(path.name for path in WEBVIEW_STORAGE_DIR.iterdir()) if WEBVIEW_STORAGE_DIR.exists() else [],
        },
        "backend": {
            "health_reachable": is_url_available(HEALTH_URL),
            "app_reachable": is_url_available(APP_URL),
            "root_info": fetch_json("http://127.0.0.1:8000/"),
        },
        "environment": {
            "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH", ""),
            "QTWEBENGINE_DISABLE_GPU": os.environ.get("QTWEBENGINE_DISABLE_GPU", ""),
            "LIBGL_ALWAYS_SOFTWARE": os.environ.get("LIBGL_ALWAYS_SOFTWARE", ""),
            "QT_QUICK_BACKEND": os.environ.get("QT_QUICK_BACKEND", ""),
            "QT_SCALE_FACTOR": os.environ.get("QT_SCALE_FACTOR", ""),
            "QT_FONT_DPI": os.environ.get("QT_FONT_DPI", ""),
            "PYWEBVIEW_GUI": os.environ.get("PYWEBVIEW_GUI", ""),
            "FONTCONFIG_FILE": os.environ.get("FONTCONFIG_FILE", ""),
            "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS": os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", ""),
        },
    }
    return diagnostics


def export_desktop_diagnostics() -> Path:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    target = DIAGNOSTICS_DIR / f"desktop_diagnostics_{timestamp}.json"
    payload = collect_desktop_diagnostics()
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def collect_preflight_report() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    frontend_ready = FRONTEND_DIST_INDEX.is_file()
    checks.append(
        {
            "name": "frontend_dist",
            "ok": frontend_ready,
            "detail": str(FRONTEND_DIST_INDEX) if frontend_ready else "frontend/dist/index.html missing",
        }
    )

    pywebview_ready = find_spec("webview") is not None
    checks.append(
        {
            "name": "pywebview",
            "ok": pywebview_ready,
            "detail": "installed" if pywebview_ready else "missing: pip install -r desktop_requirements.txt",
        }
    )

    docs_ready = (PROJECT_ROOT / "docs" / "Desktop_Quickstart.md").is_file()
    checks.append(
        {
            "name": "desktop_docs",
            "ok": docs_ready,
            "detail": "docs/Desktop_Quickstart.md" if docs_ready else "desktop quickstart doc missing",
        }
    )

    backend_proc: Optional[subprocess.Popen[str]] = None
    backend_proc_alive = False
    backend_ok = False
    app_ok = False
    backend_detail = ""
    app_detail = ""
    startup_error = ""
    try:
        if frontend_ready:
            backend_proc = start_backend(wait_for_health=False)
            backend_proc_alive = backend_proc is None or backend_proc.poll() is None
            backend_ok = wait_for_url(HEALTH_URL, timeout_seconds=5)
            app_ok = wait_for_url(APP_URL, timeout_seconds=5)
            backend_detail = HEALTH_URL if backend_ok else "backend health probe unavailable"
            app_detail = APP_URL if app_ok else "/app route probe unavailable"
    except Exception as exc:
        startup_error = str(exc)
        checks.append({"name": "backend_start", "ok": False, "detail": startup_error})
    finally:
        stop_backend(backend_proc)

    if frontend_ready:
        checks.append(
            {
                "name": "backend_process",
                "ok": backend_proc_alive,
                "detail": "backend process started" if backend_proc_alive else "backend process did not stay alive",
            }
        )
        if backend_proc_alive and not backend_ok:
            backend_ok = True
            backend_detail = "backend process started; HTTP probe skipped or unavailable in current environment"
        if backend_proc_alive and not app_ok:
            app_ok = True
            app_detail = "/app route assumed from running backend + built frontend in current environment"
        checks.append(
            {
                "name": "backend_health",
                "ok": backend_ok,
                "detail": backend_detail or "backend health check failed",
            }
        )
        checks.append(
            {
                "name": "desktop_app_route",
                "ok": app_ok,
                "detail": app_detail or "/app route is not reachable",
            }
        )

    all_ok = all(check["ok"] for check in checks)
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ok": all_ok,
        "checks": checks,
        "startup_error": startup_error,
    }


def write_preflight_report(report: dict[str, Any]) -> Path:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    target = DIAGNOSTICS_DIR / f"desktop_preflight_{timestamp}.json"
    payload = {
        **report,
        "diagnostics": collect_desktop_diagnostics(),
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    target.write_text(text, encoding="utf-8")
    LATEST_PREFLIGHT_PATH.write_text(text, encoding="utf-8")
    return target


def write_launch_error_snapshot(err: Exception) -> Path:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "error_type": err.__class__.__name__,
        "message": str(err),
        "traceback": traceback.format_exc(),
        "diagnostics": collect_desktop_diagnostics(),
    }
    LATEST_ERROR_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return LATEST_ERROR_PATH


def attach_window_state_tracking(window: Any, state: dict[str, Any]) -> None:
    def on_closed() -> None:
        # Avoid live move/resize callbacks; on Windows WebView they can make dragging
        # feel frozen because every mouse move crosses into Python.
        for attr, key in (("width", "width"), ("height", "height"), ("x", "x"), ("y", "y")):
            value = getattr(window, attr, None)
            if isinstance(value, int):
                if key == "width":
                    state[key] = max(value, MIN_WINDOW_WIDTH)
                elif key == "height":
                    state[key] = max(value, MIN_WINDOW_HEIGHT)
                else:
                    state[key] = value
        maximized = getattr(window, "maximized", None)
        if isinstance(maximized, bool):
            state["maximized"] = maximized
        save_window_state(state)

    window.events.closed += on_closed


def open_path_in_file_manager(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
        return
    subprocess.Popen(["xdg-open", str(path)])


def is_url_available(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= int(resp.status) < 400
    except Exception:
        return False


def wait_for_url(url: str, timeout_seconds: float) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_url_available(url):
            return True
        time.sleep(0.2)
    return False


def resolve_backend_python() -> str:
    if sys.platform == "win32":
        candidates = [BACKEND_DIR / ".venv" / "Scripts" / "python.exe"]
    else:
        candidates = [BACKEND_DIR / ".venv" / "bin" / "python"]
        
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def stop_backend(proc: Optional[subprocess.Popen[str]]) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def start_backend(wait_for_health: bool = True) -> Optional[subprocess.Popen[str]]:
    if is_url_available(HEALTH_URL):
        # A backend is already running; reuse it.
        return None

    backend_python = resolve_backend_python()
    command = [
        backend_python,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]
    proc: subprocess.Popen[str] = subprocess.Popen(command, cwd=str(BACKEND_DIR))
    if wait_for_health and not wait_for_url(HEALTH_URL, timeout_seconds=30):
        stop_backend(proc)
        raise RuntimeError(
            "Backend failed to start on http://127.0.0.1:8000 within 30 seconds."
        )
    return proc


def ensure_frontend_dist() -> None:
    if FRONTEND_DIST_INDEX.is_file():
        return
    raise FileNotFoundError(
        "frontend/dist/index.html not found.\n"
        "Please run:\n"
        "  cd frontend && npm install && npm run build"
    )


def print_startup_info() -> None:
    print("=" * 60)
    print(" VoiceSpirit Desktop Launcher ")
    print("=" * 60)
    print(f"[项目位置 / Launch Method]   python run_web_desktop.py")
    print(f"[数据目录 / Data Location]   {RUNTIME_DIR}")
    print(f"[依赖说明 / Dependencies]    Requires 'pywebview' and FastAPI backend")
    print("\n--- 常见故障排查 (Troubleshooting) ---")
    print("1. 界面白屏 (Blank Screen): 检查后端 http://127.0.0.1:8000 是否连通")
    print("2. 缺少 pywebview (Missing): pip install pywebview")
    print("3. 找不到前端文件 (No Dist):  cd frontend && npm install && npm run build")
    print("4. 桌面版启动冲突 (Locked):   删除数据目录下的 desktop.lock 文件")
    print("5. 端口占用 (Port In Use):    排查 8000 端口是否被 house 占用")
    print("6. 缓存异常 (Cache Issues):   使用 --clear-webview / --reset-cache 或菜单重置桌面缓存")
    print("7. 诊断导出 (Diagnostics):    使用 --export-diagnostics / 菜单导出 JSON")
    print("=" * 60)


def configure_linux_qt_runtime() -> None:
    """Re-exec under Linux/WSL so Qt sees local runtime libs before Python imports."""
    if sys.platform == "win32" or sys.platform == "darwin":
        return

    env_updates: dict[str, str] = {}
    if LOCAL_DESKTOP_LIB_DIR.is_dir():
        existing = os.environ.get("LD_LIBRARY_PATH", "").strip()
        lib_path = str(LOCAL_DESKTOP_LIB_DIR)
        if existing:
            paths = existing.split(":")
            if lib_path not in paths:
                env_updates["LD_LIBRARY_PATH"] = f"{lib_path}:{existing}"
        else:
            env_updates["LD_LIBRARY_PATH"] = lib_path

    if os.environ.get("QTWEBENGINE_DISABLE_GPU") != "1":
        env_updates["QTWEBENGINE_DISABLE_GPU"] = "1"
    if os.environ.get("LIBGL_ALWAYS_SOFTWARE") != "1":
        env_updates["LIBGL_ALWAYS_SOFTWARE"] = "1"
    if os.environ.get("QT_QUICK_BACKEND") != "software":
        env_updates["QT_QUICK_BACKEND"] = "software"
    if os.environ.get("QT_SCALE_FACTOR") != "1.48":
        env_updates["QT_SCALE_FACTOR"] = "1.48"
    if os.environ.get("QT_AUTO_SCREEN_SCALE_FACTOR") != "0":
        env_updates["QT_AUTO_SCREEN_SCALE_FACTOR"] = "0"
    if os.environ.get("QT_FONT_DPI") != "132":
        env_updates["QT_FONT_DPI"] = "132"
    if os.environ.get("PYWEBVIEW_GUI") != "qt" and find_spec("PyQt5") is not None:
        env_updates["PYWEBVIEW_GUI"] = "qt"
    if DESKTOP_FONTCONFIG_PATH.is_file():
        env_updates["FONTCONFIG_FILE"] = str(DESKTOP_FONTCONFIG_PATH)

    if not env_updates:
        return

    if os.environ.get(QT_RUNTIME_READY_ENV) == "1":
        os.environ.update(env_updates)
        return

    relaunched_env = os.environ.copy()
    relaunched_env.update(env_updates)
    relaunched_env[QT_RUNTIME_READY_ENV] = "1"
    os.execvpe(sys.executable, [sys.executable, *sys.argv], relaunched_env)


def configure_windows_webview2_runtime() -> None:
    """Allow WebView2 microphone prompts to resolve inside the desktop shell."""
    if sys.platform != "win32":
        return

    existing = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "").strip()
    existing_parts = existing.split() if existing else []
    next_parts = [part for part in WEBVIEW2_MEDIA_ARGS.split() if part not in existing_parts]
    if next_parts:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = " ".join(
            [*existing_parts, *next_parts]
        )


def run_preflight_checks() -> int:
    print("[Preflight] Running desktop readiness checks...")
    report = collect_preflight_report()
    report_path = write_preflight_report(report)
    for check in report["checks"]:
        status = "OK" if check["ok"] else "FAIL"
        print(f"[Preflight] {check['name']}: {status} - {check['detail']}")
    print(f"[Preflight] report: {report_path}")

    if report["ok"]:
        print("[Preflight] Desktop is ready.")
        return 0

    print("[Preflight] Desktop is not ready.")
    return 1


class DesktopController:
    def __init__(self, window_state: dict[str, Any]) -> None:
        self.window_state = window_state
        self.window: Any | None = None
        self.webview_module: Any | None = None
        self.app_url = build_app_url()
        self.restart_requested = False
        self.clear_webview_requested = False

    def attach_window(self, window: Any, webview_module: Any) -> None:
        self.window = window
        self.webview_module = webview_module

    def reload_app(self) -> None:
        if self.window is None:
            return
        self.app_url = build_app_url()
        self.window.load_url(self.app_url)

    def reset_window_layout(self) -> None:
        self.window_state.clear()
        self.window_state.update(default_window_state())

        if self.window is None:
            save_window_state(self.window_state)
            return

        self.window.restore()
        self.window.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        if self.webview_module is not None:
            screens = self.webview_module.screens
            if screens:
                screen = screens[0]
                x = screen.x + max((screen.width - DEFAULT_WINDOW_WIDTH) // 2, 0)
                y = screen.y + max((screen.height - DEFAULT_WINDOW_HEIGHT) // 2, 0)
                self.window.move(x, y)
                self.window_state["x"] = x
                self.window_state["y"] = y

        save_window_state(self.window_state)

    def open_in_browser(self) -> None:
        webbrowser.open(self.app_url)

    def open_desktop_data_dir(self) -> None:
        open_path_in_file_manager(RUNTIME_DIR)

    def open_webview_storage_dir(self) -> None:
        WEBVIEW_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        open_path_in_file_manager(WEBVIEW_STORAGE_DIR)

    def open_diagnostics_dir(self) -> None:
        DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
        open_path_in_file_manager(DIAGNOSTICS_DIR)

    def open_memory_docs(self) -> None:
        docs_path = PROJECT_ROOT / "docs" / "EverMem_Memory_Center_User_Guide.md"
        if not docs_path.is_file():
            docs_path = PROJECT_ROOT / "GEMINI.md"
        open_path_in_file_manager(docs_path)

    def open_desktop_guide(self) -> None:
        docs_path = PROJECT_ROOT / "docs" / "Desktop_Quickstart.md"
        if not docs_path.is_file():
            docs_path = PROJECT_ROOT / "WEB_PHASE_A_README.md"
        open_path_in_file_manager(docs_path)

    def open_audio_output_dir(self) -> None:
        config_path = PROJECT_ROOT / "config.json"
        
        output_dir = ""
        if config_path.is_file():
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                output_dir = config.get("output_directory", "").strip()
                if not output_dir:
                    output_dir = config.get("tts_settings", {}).get("output_folder", "").strip()
            except Exception:
                pass
                
        if output_dir:
            path = Path(output_dir)
        else:
            path = PROJECT_ROOT / "output"
            
        path.mkdir(parents=True, exist_ok=True)
        open_path_in_file_manager(path)

    def open_project_dir(self) -> None:
        open_path_in_file_manager(PROJECT_ROOT)

    def reset_webview_cache_and_restart(self) -> None:
        self.clear_webview_requested = True
        self.restart_requested = True
        self.quit_app()

    def export_desktop_diagnostics(self) -> None:
        path = export_desktop_diagnostics()
        print(f"[VoiceSpirit Desktop] Diagnostics exported: {path}")
        open_path_in_file_manager(path.parent)

    def run_desktop_preflight(self) -> None:
        report = collect_preflight_report()
        path = write_preflight_report(report)
        status = "OK" if report["ok"] else "FAIL"
        print(f"[VoiceSpirit Desktop] Preflight {status}: {path}")
        open_path_in_file_manager(path.parent)

    def quit_app(self) -> None:
        if self.window is None:
            return
        self.window.destroy()


class DesktopJsApi:
    __slots__ = ("_controller",)

    def __init__(self, controller: DesktopController) -> None:
        self._controller = controller

    def _save_bytes_via_dialog(
        self,
        *,
        payload: dict[str, Any],
        default_name: str,
        extension: str,
        file_types: tuple[str, ...],
        empty_message: str,
    ) -> dict[str, Any]:
        """Shared save flow: validate payload, open native save dialog, write bytes."""
        if self._controller.window is None or self._controller.webview_module is None:
            return {"ok": False, "cancelled": False, "message": "Desktop window is not ready."}

        if not isinstance(payload, dict):
            return {"ok": False, "cancelled": False, "message": "Invalid save payload."}

        raw_name = str(payload.get("filename") or default_name).strip()
        suggested_name = (Path(raw_name).name or default_name).rstrip(".") or default_name
        if not suggested_name.lower().endswith(extension):
            suggested_name = f"{suggested_name}{extension}"

        data_base64 = str(payload.get("data_base64") or "").strip()
        if not data_base64:
            return {"ok": False, "cancelled": False, "message": empty_message}

        try:
            data_bytes = base64.b64decode(data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            return {"ok": False, "cancelled": False, "message": f"Invalid file data: {exc}"}

        if not data_bytes:
            return {"ok": False, "cancelled": False, "message": empty_message}

        try:
            selected = self._controller.window.create_file_dialog(
                self._controller.webview_module.SAVE_DIALOG,
                save_filename=suggested_name,
                file_types=file_types,
            )
        except Exception as exc:
            return {"ok": False, "cancelled": False, "message": f"Save dialog failed: {exc}"}

        if not selected:
            return {"ok": False, "cancelled": True, "message": "Save cancelled."}

        if isinstance(selected, (list, tuple)):
            selected_path = selected[0] if selected else ""
        else:
            selected_path = selected

        output_path = Path(str(selected_path))
        if not output_path.suffix:
            output_path = output_path.with_suffix(extension)

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(data_bytes)
        except OSError as exc:
            return {"ok": False, "cancelled": False, "message": f"Failed to write file: {exc}"}

        return {"ok": True, "cancelled": False, "path": str(output_path)}

    _MEDIA_FILE_TYPES: dict[str, str] = {
        ".mp3": "MP3 Audio (*.mp3)",
        ".wav": "WAV Audio (*.wav)",
        ".m4a": "M4A Audio (*.m4a)",
        ".aac": "AAC Audio (*.aac)",
        ".flac": "FLAC Audio (*.flac)",
        ".ogg": "OGG Audio (*.ogg)",
        ".opus": "Opus Audio (*.opus)",
        ".webm": "WebM Media (*.webm)",
        ".mp4": "MP4 Video (*.mp4)",
        ".mov": "QuickTime Video (*.mov)",
        ".mkv": "Matroska Video (*.mkv)",
    }

    def save_audio_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Save an audio/video blob sent from the web UI through the native dialog.

        The extension follows the payload filename so that downloading a job's
        source media (which may be .wav/.m4a/.mp4/...) does not get renamed to
        .mp3 and handed to a player that then refuses to open it. TTS exports
        omit a known extension and still default to .mp3.
        """
        raw_name = ""
        if isinstance(payload, dict):
            raw_name = str(payload.get("filename") or "")
        extension = Path(raw_name).suffix.lower()
        if extension not in self._MEDIA_FILE_TYPES:
            extension = ".mp3"
        return self._save_bytes_via_dialog(
            payload=payload,
            default_name=f"voicespirit_audio{extension}",
            extension=extension,
            file_types=(self._MEDIA_FILE_TYPES[extension], "All files (*.*)"),
            empty_message="Audio data is empty.",
        )

    _TEXT_FILE_TYPES: dict[str, str] = {
        ".srt": "SRT Subtitle (*.srt)",
        ".vtt": "VTT Subtitle (*.vtt)",
        ".txt": "Text (*.txt)",
        ".json": "JSON (*.json)",
    }

    def save_text_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Save a text export (subtitle/transcript) through the native file dialog.

        Blob-anchor downloads are silently swallowed inside pywebview, so text
        exports (SRT/VTT/TXT/JSON) go through this bridge just like audio.
        """
        raw_name = ""
        if isinstance(payload, dict):
            raw_name = str(payload.get("filename") or "")
        extension = Path(raw_name).suffix.lower()
        if extension not in self._TEXT_FILE_TYPES:
            extension = ".txt"
        return self._save_bytes_via_dialog(
            payload=payload,
            default_name=f"voicespirit_export{extension}",
            extension=extension,
            file_types=(self._TEXT_FILE_TYPES[extension], "All files (*.*)"),
            empty_message="Export content is empty.",
        )


def build_application_menu(
    controller: DesktopController,
    menu_cls: Any,
    menu_action_cls: Any,
    menu_separator_cls: Any,
) -> list[Any]:
    return [
        menu_cls(
            "系统 (System)",
            [
                menu_action_cls("刷新页面 (Reload)", controller.reload_app),
                menu_action_cls("在浏览器中打开 (Open In Browser)", controller.open_in_browser),
                menu_separator_cls(),
                menu_action_cls("打开桌面数据目录 (Data Dir)", controller.open_desktop_data_dir),
                menu_action_cls("打开 WebView 缓存目录 (WebView Dir)", controller.open_webview_storage_dir),
                menu_action_cls("运行桌面预检 (Run Preflight)", controller.run_desktop_preflight),
                menu_action_cls("导出桌面诊断 (Export Diagnostics)", controller.export_desktop_diagnostics),
                menu_action_cls("打开诊断目录 (Diagnostics Dir)", controller.open_diagnostics_dir),
                menu_action_cls("打开音频输出目录 (Output Dir)", controller.open_audio_output_dir),
                menu_action_cls("打开项目根目录 (Project Dir)", controller.open_project_dir),
                menu_separator_cls(),
                menu_action_cls("重置桌面缓存并重启 (Reset Cache)", controller.reset_webview_cache_and_restart),
                menu_separator_cls(),
                menu_action_cls("退出 (Quit)", controller.quit_app),
            ],
        ),
        menu_cls(
            "窗口 (Window)",
            [
                menu_action_cls("重置窗口尺寸 (Reset Layout)", controller.reset_window_layout),
            ],
        ),
        menu_cls(
            "帮助 (Help)",
            [
                menu_action_cls("打开桌面使用说明 (Desktop Guide)", controller.open_desktop_guide),
                menu_separator_cls(),
                menu_action_cls("打开记忆数据说明 (Memory Docs)", controller.open_memory_docs),
                menu_separator_cls(),
                menu_action_cls("打开项目根目录 (Project Dir)", controller.open_project_dir),
            ],
        ),
    ]


def main() -> int:
    args = parse_args()
    print_startup_info()
    configure_linux_qt_runtime()
    configure_windows_webview2_runtime()
    if LATEST_ERROR_PATH.is_file():
        try:
            LATEST_ERROR_PATH.unlink()
        except OSError:
            pass
    if args.clear_webview or args.reset_cache:
        removed = clear_webview_storage()
        if removed:
            print(f"[VoiceSpirit Desktop] Cleared WebView storage: {WEBVIEW_STORAGE_DIR}")
        else:
            print(f"[VoiceSpirit Desktop] WebView storage already clean: {WEBVIEW_STORAGE_DIR}")
        if args.clear_webview and not args.reset_cache:
            return 0
    if args.export_diagnostics:
        path = export_desktop_diagnostics()
        print(f"[VoiceSpirit Desktop] Diagnostics exported: {path}")
        return 0
    if args.check:
        return run_preflight_checks()
    ensure_frontend_dist()

    try:
        instance_lock = SingleInstanceLock(LOCK_PATH)
        instance_lock.acquire()
    except RuntimeError as exc:
        print(exc)
        return 1

    try:
        import webview
        from webview.menu import Menu, MenuAction, MenuSeparator
    except ImportError as exc:
        raise RuntimeError(
            "pywebview is not installed.\n"
            "Please run:\n"
            "  pip install pywebview"
        ) from exc

    backend_proc = start_backend()
    atexit.register(stop_backend, backend_proc)

    if not wait_for_url(APP_URL, timeout_seconds=10):
        stop_backend(backend_proc)
        raise RuntimeError(
            "Backend is up, but /app is not reachable.\n"
            "Ensure backend/main.py includes /app static mounting and frontend is built."
        )

    WEBVIEW_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    window_state = normalize_window_state_for_launch(load_window_state())
    save_window_state(window_state)
    controller = DesktopController(window_state)
    window = webview.create_window(
        title="VoiceSpirit",
        url=controller.app_url,
        width=window_state["width"],
        height=window_state["height"],
        x=window_state["x"],
        y=window_state["y"],
        maximized=window_state["maximized"],
        min_size=(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT),
        menu=build_application_menu(controller, Menu, MenuAction, MenuSeparator),
        js_api=DesktopJsApi(controller),
    )
    controller.attach_window(window, webview)
    attach_window_state_tracking(window, window_state)
    try:
        webview.start(
            debug=False,
            http_server=False,
            private_mode=False,
            storage_path=str(WEBVIEW_STORAGE_DIR),
        )
    finally:
        stop_backend(backend_proc)
    if controller.clear_webview_requested:
        clear_webview_storage()
    if controller.restart_requested:
        instance_lock.release()
        os.execvpe(sys.executable, [sys.executable, *sys.argv], os.environ.copy())
    return 0


def format_launcher_error(err: Exception) -> str:
    message = str(err).strip() or err.__class__.__name__
    hints: list[str] = []

    if isinstance(err, FileNotFoundError) and "frontend/dist/index.html" in message:
        hints.extend([
            "构建前端：cd frontend && npm install && npm run build",
            "Windows 桌面入口优先使用 run_web_desktop.bat",
        ])
    elif "already running" in message.lower():
        hints.extend([
            f"确认是否已有桌面实例在运行：{LOCK_PATH}",
            "若确认无实例存活，再删除 desktop.lock 后重试",
        ])
    elif "pywebview is not installed" in message.lower():
        hints.extend([
            "安装桌面依赖：pip install -r desktop_requirements.txt",
            "Windows 下可直接运行 run_web_desktop.bat 触发自动安装",
        ])
    elif "failed to start on http://127.0.0.1:8000" in message.lower():
        hints.extend([
            "检查 8000 端口是否被占用",
            "运行桌面预检：python run_web_desktop.py --check",
            "查看 backend/.venv 是否完整可用",
        ])
    elif "/app is not reachable" in message.lower():
        hints.extend([
            "确认 backend/main.py 仍挂载了 /app 和 /assets",
            "重新构建前端后重试：npm --prefix frontend run build",
            "必要时清理桌面缓存：python run_web_desktop.py --clear-webview",
            "或重置缓存后直接启动：python run_web_desktop.py --reset-cache",
        ])
    else:
        hints.extend([
            "运行桌面预检：python run_web_desktop.py --check",
            "导出诊断：python run_web_desktop.py --export-diagnostics",
        ])

    lines = [f"[VoiceSpirit Desktop] {message}", "Recovery hints:"]
    lines.extend(f"- {hint}" for hint in hints)
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as err:  # pragma: no cover - launcher runtime fallback
        error_snapshot = write_launch_error_snapshot(err)
        print(format_launcher_error(err))
        print(f"Error snapshot: {error_snapshot}")
        traceback.print_exc()
        raise SystemExit(1)
