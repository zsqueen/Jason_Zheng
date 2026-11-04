@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Python environment is missing. Please reinstall dependencies.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -c "import runpy; runpy.run_path('\u684c\u5ba0.py', run_name='__main__')"
