@echo off
echo ====================================================
echo Building Python Backend using PyInstaller...
echo ====================================================

cd backend

:: Use conda python if it exists, or local virtual env
set PYTHON_EXE=python
if exist D:\conda\python.exe (
    set PYTHON_EXE=D:\conda\python.exe
) else if exist .venv\Scripts\python.exe (
    set PYTHON_EXE=.venv\Scripts\python.exe
) else if exist ..\venv\Scripts\python.exe (
    set PYTHON_EXE=..\venv\Scripts\python.exe
)

echo Using Python: %PYTHON_EXE%

%PYTHON_EXE% -m pip install setuptools pyinstaller -r requirements.txt

:: Clean up old builds
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

:: Run PyInstaller with heavy modules excluded to prevent massive bloat
%PYTHON_EXE% -m PyInstaller --name voicespirit-backend --onedir --console main.py ^
    --hidden-import=uvicorn.logging ^
    --hidden-import=uvicorn.loops.auto ^
    --hidden-import=uvicorn.protocols.http.auto ^
    --hidden-import=uvicorn.protocols.websockets.auto ^
    --hidden-import=websockets.legacy.auth ^
    --hidden-import=pydub ^
    --hidden-import=pydub.utils ^
    --hidden-import=pydub.generators ^
    --hidden-import=edge_tts ^
    --hidden-import=dashscope ^
    --hidden-import=openai ^
    --hidden-import=aiohttp ^
    --hidden-import=sqlite3 ^
    --exclude-module=torch ^
    --exclude-module=torchvision ^
    --exclude-module=torchaudio ^
    --exclude-module=numpy ^
    --exclude-module=scipy ^
    --exclude-module=matplotlib ^
    --exclude-module=pandas ^
    --exclude-module=pygame ^
    --exclude-module=PIL ^
    --exclude-module=sympy ^
    --exclude-module=jinja2 ^
    --exclude-module=IPython ^
    --exclude-module=jedi ^
    --exclude-module=parso ^
    --exclude-module=pytest ^
    --exclude-module=lxml

if %errorlevel% neq 0 (
    echo Backend Build Failed!
    cd ..
    exit /b %errorlevel%
)

echo Backend Build Success!
cd ..
