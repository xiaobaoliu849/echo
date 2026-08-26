from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_NAME = "Echo"


def _dedupe_text(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _build_launch_error_hints(error_type: str, message: str) -> list[str]:
    error_name = str(error_type or "").strip()
    text = str(message or "").strip()
    lowered = text.lower()

    if error_name == "FileNotFoundError" and "frontend/dist/index.html" in text:
        return [
            "构建前端：npm --prefix frontend run build",
            "Windows 桌面入口优先使用 run_web_desktop.bat",
        ]
    if "already running" in lowered:
        return [
            "确认是否已有桌面实例在运行，再检查 runtime 目录中的 desktop.lock",
            "若确认无实例存活，再删除 desktop.lock 后重试",
        ]
    if "pywebview is not installed" in lowered:
        return [
            "安装桌面依赖：pip install -r desktop_requirements.txt",
            "Windows 下可直接运行 run_web_desktop.bat 触发自动安装",
        ]
    if "failed to start on http://127.0.0.1:8000" in lowered:
        return [
            "检查 8000 端口是否被占用",
            "运行桌面预检：python run_web_desktop.py --check",
            "查看 backend/.venv 是否完整可用",
        ]
    if "/app is not reachable" in lowered:
        return [
            "确认 backend/main.py 仍挂载了 /app 和 /assets",
            "重新构建前端后重试：npm --prefix frontend run build",
            "必要时清理桌面缓存：python run_web_desktop.py --clear-webview",
        ]
    return [
        "运行桌面预检：python run_web_desktop.py --check",
        "导出诊断：python run_web_desktop.py --export-diagnostics",
    ]


def _build_preflight_hints(name: str, detail: str) -> list[str]:
    check_name = str(name or "").strip()
    detail_text = str(detail or "").strip()
    lowered = detail_text.lower()

    if check_name == "frontend_dist":
        return [
            "重新构建前端：npm --prefix frontend run build",
            "Windows 下优先通过 run_web_desktop.bat 启动桌面",
        ]
    if check_name == "pywebview":
        return [
            "安装桌面依赖：pip install -r desktop_requirements.txt",
            "确认当前桌面 Python 环境能导入 pywebview",
        ]
    if check_name == "desktop_docs":
        return [
            "确认 docs/Desktop_Quickstart.md 仍存在，避免桌面帮助入口失效",
        ]
    if check_name in {"backend_start", "backend_process", "backend_health"}:
        hints = [
            "运行桌面预检：python run_web_desktop.py --check",
            "确认 http://127.0.0.1:8000/health 可访问",
            "检查 backend/.venv 和后端依赖是否完整",
        ]
        if "8000" in lowered:
            hints.insert(0, "检查 8000 端口是否被其他进程占用")
        return hints
    if check_name == "desktop_app_route":
        return [
            "确认 backend/main.py 仍挂载了 /app 和 /assets",
            "重新构建前端：npm --prefix frontend run build",
            "必要时清理桌面缓存：python run_web_desktop.py --clear-webview",
        ]
    return []


def is_wsl_environment() -> bool:
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text(encoding="utf-8").lower()
    except OSError:
        return False


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
            preferred_dir = PROJECT_ROOT / ".voicespirit-state" / APP_NAME
            fallback_dir = PROJECT_ROOT / ".voicespirit-desktop"
        else:
            xdg_state_home = os.environ.get("XDG_STATE_HOME")
            base_dir = Path(xdg_state_home) if xdg_state_home else Path.home() / ".local" / "state"
            preferred_dir = base_dir / APP_NAME
            fallback_dir = PROJECT_ROOT / ".voicespirit-desktop"

    for candidate in (preferred_dir, fallback_dir):
        if candidate.exists():
            return candidate
    return preferred_dir


class DesktopDiagnosticsService:
    def __init__(self) -> None:
        self.runtime_dir = get_runtime_dir()
        self.diagnostics_dir = self.runtime_dir / "diagnostics"
        self.preflight_path = self.diagnostics_dir / "desktop_preflight_latest.json"
        self.launch_error_path = self.diagnostics_dir / "desktop_launch_error_latest.json"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    def get_status(self) -> dict[str, Any]:
        preflight = self._read_json(self.preflight_path) or {}
        launch_error = self._read_json(self.launch_error_path) or {}
        preflight_checks = preflight.get("checks", [])
        failed_checks = [
            {
                "name": str(item.get("name", "")),
                "detail": str(item.get("detail", "")),
            }
            for item in preflight_checks
            if isinstance(item, dict) and not bool(item.get("ok", False))
        ]
        latest_error_hints = []
        if launch_error:
            latest_error_hints.extend(
                _build_launch_error_hints(
                    str(launch_error.get("error_type", "")),
                    str(launch_error.get("message", "")),
                )
            )
            for item in failed_checks:
                latest_error_hints.extend(
                    _build_preflight_hints(item.get("name", ""), item.get("detail", ""))
                )
        latest_error_hints = _dedupe_text(latest_error_hints)

        return {
            "runtime_dir": str(self.runtime_dir),
            "diagnostics_dir": str(self.diagnostics_dir),
            "preflight": {
                "available": bool(preflight),
                "ok": bool(preflight.get("ok", False)) if preflight else None,
                "timestamp": str(preflight.get("timestamp", "")) if preflight else "",
                "failed_checks": failed_checks,
                "failed_count": len(failed_checks),
            },
            "latest_error": {
                "available": bool(launch_error),
                "timestamp": str(launch_error.get("timestamp", "")) if launch_error else "",
                "error_type": str(launch_error.get("error_type", "")) if launch_error else "",
                "message": str(launch_error.get("message", "")) if launch_error else "",
                "recovery_hints": latest_error_hints,
            },
        }
