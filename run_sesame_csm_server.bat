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

set "PYTHON_EXE=C:\pp-eval\venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

netstat -ano | findstr :8997 >nul 2>&1
if not errorlevel 1 (
    echo [NOTICE] Cleaning up previous process on port 8997...
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8997 ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    timeout /t 2 /nobreak >nul
)

set "PYTHONPATH=C:\pp-eval\csm;%PYTHONPATH%"
"%PYTHON_EXE%" "C:\pp-eval\csm\csm_server.py" --host 127.0.0.1 --port 8997

if errorlevel 1 (
    echo.
    echo [ERROR] Sesame CSM-1B server exited with code %errorlevel%.
    echo.
)

echo.
echo Server window paused. Press any key to close...
pause
