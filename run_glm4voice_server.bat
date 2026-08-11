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

set "PYTHON_EXE=C:\pp-eval\venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

netstat -ano | findstr :8999 >nul 2>&1
if not errorlevel 1 (
    echo [NOTICE] Cleaning up previous process on port 8999...
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8999 ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    timeout /t 2 /nobreak >nul
)

set "LOCAL_MODEL_PATH=C:\Users\WINDOWS\.cache\modelscope\models\ZhipuAI--glm-4-voice-9b\snapshots\master"
if not exist "%LOCAL_MODEL_PATH%" (
    set "LOCAL_MODEL_PATH=THUDM/glm-4-voice-9b"
)

set "PYTHONPATH=C:\pp-eval\GLM-4-Voice;%PYTHONPATH%"
"%PYTHON_EXE%" "C:\pp-eval\GLM-4-Voice\model_server.py" --host 127.0.0.1 --port 8999 --model-path "%LOCAL_MODEL_PATH%" --dtype int4

if errorlevel 1 (
    echo.
    echo [ERROR] GLM-4-Voice server exited with code %errorlevel%.
    echo.
)

echo.
echo Server window paused. Press any key to close...
pause
