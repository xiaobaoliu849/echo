@echo off
setlocal EnableExtensions EnableDelayedExpansion

echo Starting VoiceSpirit Desktop (PyWebView)...
echo.

cd /d "%~dp0"

set "PYEXE="
set "PYARGS="
if exist backend\.venv\Scripts\python.exe (
  set "PYEXE=backend\.venv\Scripts\python.exe"
) else if exist venv\Scripts\python.exe (
  set "PYEXE=venv\Scripts\python.exe"
) else if exist backend\venv\Scripts\python.exe (
  set "PYEXE=backend\venv\Scripts\python.exe"
) else (
  py -3 -c "import sys" >nul 2>nul
  if not errorlevel 1 (
    set "PYEXE=py"
    set "PYARGS=-3"
  ) else (
    set "PYEXE=python"
    set "PYARGS="
  )
)

echo Using Python launcher: %PYEXE% %PYARGS%

call "%PYEXE%" %PYARGS% -c "import webview" >nul 2>nul
if errorlevel 1 (
  echo pywebview not found in current Python. Installing desktop dependencies...
  call "%PYEXE%" %PYARGS% -m ensurepip --upgrade >nul 2>nul
  call "%PYEXE%" %PYARGS% -m pip --version >nul 2>nul
  if errorlevel 1 (
    echo pip is unavailable in current Python runtime.
    goto :fail
  )
  call "%PYEXE%" %PYARGS% -m pip install --upgrade pip setuptools wheel
  if errorlevel 1 goto :fail
  call "%PYEXE%" %PYARGS% -m pip install -r desktop_requirements.txt
  if errorlevel 1 goto :fail
  call "%PYEXE%" %PYARGS% -c "import webview" >nul 2>nul
  if errorlevel 1 goto :fail
)

echo Building frontend before desktop launch...
call npm --prefix frontend run build
if errorlevel 1 (
  echo Frontend build failed. Desktop launch cancelled.
  goto :fail
)

call "%PYEXE%" %PYARGS% run_web_desktop.py %*
if errorlevel 1 goto :fail

echo VoiceSpirit Desktop exited.
exit /b 0

:fail
echo.
echo Desktop launcher exited with errors.
echo.
echo Manual fallback:
echo   "%PYEXE%" %PYARGS% -m ensurepip --upgrade
echo   "%PYEXE%" %PYARGS% -m pip install --upgrade pip setuptools wheel
echo   "%PYEXE%" %PYARGS% -m pip install -r desktop_requirements.txt
echo   npm --prefix frontend run build
echo   "%PYEXE%" %PYARGS% run_web_desktop.py --export-diagnostics
echo   "%PYEXE%" %PYARGS% run_web_desktop.py %*
echo.
pause
exit /b 1
