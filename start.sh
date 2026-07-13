#!/usr/bin/env bash
# AccessAudit — one-command launcher.
# Sets up dependencies (first run only), starts the server, opens your browser.

set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "First-time setup — creating a virtual environment and installing dependencies..."
  python3 -m venv .venv
fi

source .venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "Starting AccessAudit..."
echo "Opening http://127.0.0.1:8010 in your browser..."
echo "(Press Ctrl+C here to stop the server)"
echo ""

( sleep 1.5 && python3 -m webbrowser "http://127.0.0.1:8010" ) &

uvicorn webapp.main:app --host 127.0.0.1 --port 8010
