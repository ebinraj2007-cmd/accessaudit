@echo off
REM AccessAudit — one-command launcher for Windows.
cd /d "%~dp0"

if not exist ".venv" (
    echo First-time setup — creating a virtual environment and installing dependencies...
    python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install -q -r requirements.txt

echo.
echo Starting AccessAudit...
echo Opening http://127.0.0.1:8010 in your browser...
echo (Close this window to stop the server)
echo.

start "" "http://127.0.0.1:8010"
uvicorn webapp.main:app --host 127.0.0.1 --port 8010
