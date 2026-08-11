@echo off
setlocal EnableExtensions

echo =========================================================
echo   Starting GLM-4-Voice (THUDM 9B) Local Server
echo =========================================================
echo.
echo Model        : GLM-4-Voice-9B (Zhipu AI)
echo Mode         : Local Native Speech-to-Speech (Bilingual)
echo Port         : 8999 (ws://127.0.0.1:8999)
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

netstat -ano | findstr :8999 >nul 2>&1
if not errorlevel 1 (
    echo [NOTICE] Cleaning up previous process on port 8999...
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8999 ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    timeout /t 2 /nobreak >nul
)

"%PYTHON_EXE%" -m glm4voice.server --host 127.0.0.1 --port 8999

if errorlevel 1 (
    echo.
    echo [ERROR] GLM-4-Voice server exited with code %errorlevel%.
    echo.
)

echo.
echo Server window paused. Press any key to close...
pause
