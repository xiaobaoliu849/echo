@echo off
setlocal EnableExtensions

echo =========================================================
echo   Starting Sesame CSM-1B (Sesame AI 1B) Local Server
echo =========================================================
echo.
echo Model        : Sesame CSM-1B (Conversational Speech Model)
echo Mode         : Local Native Speech-to-Speech (Fast English)
echo Port         : 8997 (ws://127.0.0.1:8997)
echo.

set "NO_TORCH_COMPILE=1"
set "PYTHON_EXE=python"

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python environment not found in PATH.
    echo.
    pause
    exit /b 1
)

netstat -ano | findstr :8997 >nul 2>&1
if not errorlevel 1 (
    echo [NOTICE] Cleaning up previous process on port 8997...
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8997 ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    timeout /t 2 /nobreak >nul
)

"%PYTHON_EXE%" -m csm.server --host 127.0.0.1 --port 8997

if errorlevel 1 (
    echo.
    echo [ERROR] Sesame CSM-1B server exited with code %errorlevel%.
    echo.
)

echo.
echo Server window paused. Press any key to close...
pause
