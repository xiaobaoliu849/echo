@echo off
echo ====================================================
echo Starting VoiceSpirit Full Desktop Build Workflow
echo ====================================================

:: 1. Build Frontend
echo [1/3] Building React Frontend...
call npm --prefix frontend run build
if %errorlevel% neq 0 (
    echo Frontend Build Failed!
    exit /b %errorlevel%
)

:: 2. Build Python Backend
echo [2/3] Building Python Backend...
call build_backend.bat
if %errorlevel% neq 0 (
    echo Backend Build Failed!
    exit /b %errorlevel%
)

:: 3. Build Electron App
echo [3/3] Building Electron App...
cd electron
call npm install
call npm run build
if %errorlevel% neq 0 (
    echo Electron Build Failed!
    exit /b %errorlevel%
)

echo ====================================================
echo VoiceSpirit Desktop Build Completed Successfully!
echo Installer is located in: electron\dist\
echo ====================================================
cd ..
