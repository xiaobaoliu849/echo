@echo off
setlocal EnableExtensions

echo =========================================================
echo   Starting GLM-4-Voice (THUDM 9B) Local Real-time Server
echo =========================================================
echo.
echo Model        : GLM-4-Voice-9B (Zhipu AI)
echo Mode         : End-to-End Speech-to-Speech (Bilingual)
echo S2S Endpoint : ws://127.0.0.1:8999/api/chat
echo LLM Worker   : http://127.0.0.1:10000/generate_stream
echo.

set "PYTHON_EXE=C:\pp-eval\venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

set "GLM_ROOT=C:\pp-eval\GLM-4-Voice"
rem Never leave a trailing ";" here. An empty ambient PYTHONPATH would turn into a
rem whitespace-only search-path entry further down, and CPython aborts at startup
rem with "OSError: failed to make path absolute" / "Fatal Python error: error
rem evaluating path" before any user code runs.
if defined PYTHONPATH (
    set "PYTHONPATH=%GLM_ROOT%;%GLM_ROOT%\third_party\Matcha-TTS;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%GLM_ROOT%;%GLM_ROOT%\third_party\Matcha-TTS"
)
set "LOCAL_MODEL_PATH=C:\Users\WINDOWS\.cache\modelscope\models\ZhipuAI--glm-4-voice-9b\snapshots\master"
if not exist "%LOCAL_MODEL_PATH%" (
    set "LOCAL_MODEL_PATH=C:\Users\WINDOWS\.cache\modelscope\models\THUDM--glm-4-voice-9b\snapshots\master"
)
if not exist "%LOCAL_MODEL_PATH%" (
    set "LOCAL_MODEL_PATH=THUDM/glm-4-voice-9b"
)

set "LOCAL_TOKENIZER_PATH=C:\Users\WINDOWS\.cache\modelscope\models\ZhipuAI--glm-4-voice-tokenizer\snapshots\master"
if not exist "%LOCAL_TOKENIZER_PATH%" (
    set "LOCAL_TOKENIZER_PATH=C:\Users\WINDOWS\.cache\modelscope\models\THUDM--glm-4-voice-tokenizer\snapshots\master"
)

set "LOCAL_DECODER_PATH=C:\Users\WINDOWS\.cache\modelscope\models\ZhipuAI--glm-4-voice-decoder\snapshots\master"
if not exist "%LOCAL_DECODER_PATH%\flow.pt" (
    echo [ERROR] GLM-4-Voice decoder not found at %LOCAL_DECODER_PATH%
    echo         Please download ZhipuAI/glm-4-voice-decoder via ModelScope.
    pause
    exit /b 1
)

echo Cleaning up stale processes on ports 8999 / 10000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8999 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :10000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 2 /nobreak >nul

echo Ensuring pinned dependency versions (transformers 4.44.1 / accelerate 0.33.0)...
"%PYTHON_EXE%" -c "import transformers, accelerate; assert transformers.__version__ == '4.44.1', transformers.__version__; assert accelerate.__version__ == '0.33.0', accelerate.__version__" >nul 2>&1
if errorlevel 1 (
    echo Installing pinned transformers 4.44.1 / accelerate 0.33.0 required by GLM-4-Voice 9B...
    "%PYTHON_EXE%" -m pip install "transformers==4.44.1" "accelerate==0.33.0"
    if errorlevel 1 (
        echo [ERROR] Failed to install pinned transformers/accelerate.
        pause
        exit /b 1
    )
)
"%PYTHON_EXE%" -c "import numpy; assert int(numpy.__version__.split('.')[0]) < 2, numpy.__version__" >nul 2>&1
if errorlevel 1 (
    echo Installing numpy 1.x required by GLM-4-Voice decoder...
    "%PYTHON_EXE%" -m pip install "numpy<2"
    if errorlevel 1 (
        echo [ERROR] Failed to install numpy 1.x.
        pause
        exit /b 1
    )
)
"%PYTHON_EXE%" -c "import scipy; assert int(scipy.__version__.split('.')[0]) < 2, scipy.__version__" >nul 2>&1
if errorlevel 1 (
    echo Installing scipy 1.13.1 compatible with numpy 1.x...
    "%PYTHON_EXE%" -m pip install "scipy==1.13.1"
    if errorlevel 1 (
        echo [ERROR] Failed to install scipy 1.13.1.
        pause
        exit /b 1
    )
)
"%PYTHON_EXE%" -c "import hyperpyyaml" >nul 2>&1
if errorlevel 1 (
    "%PYTHON_EXE%" -m pip install hyperpyyaml
    if errorlevel 1 (
        echo [ERROR] Failed to install hyperpyyaml.
        pause
        exit /b 1
    )
)
"%PYTHON_EXE%" -c "import conformer" >nul 2>&1
if errorlevel 1 (
    "%PYTHON_EXE%" -m pip install conformer==0.3.2
    if errorlevel 1 (
        echo [ERROR] Failed to install conformer.
        pause
        exit /b 1
    )
)

echo Starting GLM-4-Voice LLM Worker on port 10000 (background window)...
rem The worker inherits PYTHONPATH from this script, so do NOT re-set it inside the
rem cmd /k string: an unquoted "set VAR=value && ..." swallows the space before the
rem "&&" into the value, appending a whitespace-only entry that kills the interpreter.
start "GLM-4-Voice LLM Worker" /min cmd /k ""%PYTHON_EXE%" "%GLM_ROOT%\model_server.py" --host 127.0.0.1 --port 10000 --model-path "%LOCAL_MODEL_PATH%" --dtype int4 > "%~dp0glm4voice_worker.log" 2>&1"

echo Waiting for GLM-4-Voice LLM Worker to be ready (port 10000, up to 120s)...
set /a LLM_WAIT=0
:wait_llm
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :10000 ^| findstr LISTENING') do goto llm_ready
timeout /t 3 /nobreak >nul
set /a LLM_WAIT+=3
if %LLM_WAIT% LSS 120 goto wait_llm
echo [WARNING] LLM Worker did not report ready within 120s; starting S2S anyway...
:llm_ready
echo LLM Worker ready. Starting GLM-4-Voice S2S Server on port 8999...
"%PYTHON_EXE%" "%~dp0glm4voice_s2s_server.py" --tokenizer-path "%LOCAL_TOKENIZER_PATH%" --model-path "%LOCAL_MODEL_PATH%" --flow-path "%LOCAL_DECODER_PATH%" --llm-url http://127.0.0.1:10000/generate_stream --host 127.0.0.1 --port 8999 --device cuda

echo.
echo [INFO] Cleaning up GLM-4-Voice LLM Worker (port 10000)...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :10000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

echo.
echo Server window paused. Press any key to close...
pause
