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
    pause
    exit /b 1
)

netstat -ano | findstr :8998 >nul 2>&1
if not errorlevel 1 (
    echo [NOTICE] Port 8998 is already in use (PersonaPlex server is already running!).
    echo.
)

"%PYTHON_EXE%" -m moshi.server --host 127.0.0.1 --port 8998 --moshi-weight "C:\pp-eval\model_bnb_4bit.pt" --quantize-4bit --voice-prompt-dir "C:\pp-eval\voices\voices"

pause
