@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>&1
if %errorlevel%==0 (
  set "BOOT=py -3"
) else (
  where python >nul 2>&1
  if errorlevel 1 (
    echo Install Python 3.11 or newer from https://www.python.org/downloads/
    echo On the installer, check "Add python.exe to PATH".
    pause
    exit /b 1
  )
  set "BOOT=python"
)

if not exist ".venv\Scripts\python.exe" (
  echo Setting up Retail Rivals. The first launch installs the desk and can take a minute.
  %BOOT% -m venv .venv
  if errorlevel 1 (
    echo Could not create the Python environment.
    pause
    exit /b 1
  )
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo Could not install the game.
    pause
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m open_late
if errorlevel 1 pause
endlocal
