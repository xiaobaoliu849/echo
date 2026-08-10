@echo off
setlocal EnableExtensions

echo =========================================================
echo   Starting PersonaPlex (NVIDIA 7B 4-bit) Local Server
echo =========================================================
echo.
echo Model Weight : C:\pp-eval\model_bnb_4bit.pt
echo Voice Prompt : C:\pp-eval\voices\voices
echo Port         : 8998 (ws://127.0.0.1:8998)
echo.

set "NO_TORCH_COMPILE=1"
set "PYTHON_EXE=C:\pp-eval\venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo [ERROR] Python environment not found at C:\pp-eval\venv\Scripts\python.exe
    echo.
    pause
    exit /b 1
)

netstat -ano | findstr :8998 >nul 2>&1
if not errorlevel 1 (
    echo [NOTICE] Cleaning up previous process on port 8998...
    for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8998 ^| findstr LISTENING') do (
        taskkill /F /PID %%a >nul 2>&1
    )
    timeout /t 2 /nobreak >nul
)

"%PYTHON_EXE%" -m moshi.server --host 127.0.0.1 --port 8998 --moshi-weight "C:\pp-eval\model_bnb_4bit.pt" --quantize-4bit --voice-prompt-dir "C:\pp-eval\voices\voices"

if errorlevel 1 (
    echo.
    echo [ERROR] PersonaPlex server exited with code %errorlevel%.
    echo.
)

echo.
echo Server window paused. Press any key to close...
pause
