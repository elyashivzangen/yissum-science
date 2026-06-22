@echo off
setlocal
cd /d "%~dp0"
title IBKR Israel Tax App

echo ================================================
echo IBKR Israel Tax App - launcher
echo ================================================
echo.

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PY=py -3"
) else (
  set "PY=python"
)

%PY% --version >nul 2>nul
if not %ERRORLEVEL%==0 (
  echo Python was not found.
  echo Install Python 3.10 or newer from https://www.python.org/downloads/
  echo During installation, check "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating local Python environment...
  %PY% -m venv .venv
  if not %ERRORLEVEL%==0 (
    echo Failed to create virtual environment.
    pause
    exit /b 1
  )
)

call ".venv\Scripts\activate.bat"
echo Installing/updating dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if not %ERRORLEVEL%==0 (
  echo Dependency installation failed.
  pause
  exit /b 1
)

echo.
echo Opening the app in your browser...
echo If the browser does not open automatically, go to http://localhost:8501
python -m streamlit run app.py

echo.
echo App closed.
pause
