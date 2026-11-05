@echo off
cd /d "%~dp0"
set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    where python >nul 2>nul
    if errorlevel 1 (
        where py >nul 2>nul
        if errorlevel 1 (
            echo Python is missing. Please install Python 3.11 or newer.
            pause
            exit /b 1
        )
        set "PYTHON=py -3"
    ) else (
        set "PYTHON=python"
    )
)
%PYTHON% -c "import os, sys, subprocess; import PySide6, requests, psutil; subprocess.Popen([os.path.join(os.path.dirname(sys.executable), 'pythonw.exe'), '\u684c\u5ba0.py'])"
if errorlevel 1 (
    echo Startup failed. Install dependencies with: %PYTHON% -m pip install -r requirements.txt
    pause
    exit /b 1
)
