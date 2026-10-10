#!/usr/bin/env bash
# Render.com startup script: installs headless Chromium deps, then serves the FastAPI app.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Ensure server environment flags are strictly active
export IS_SERVER="true"
export HEADLESS="true"
export BROWSER_MODE="headless"
export BROWSER_TYPE="chromium"

echo "[startup] Installing Playwright Chromium for headless execution..."
python -m playwright install chromium --with-deps || python -m playwright install chromium

echo "[startup] Launching FastAPI backend on port ${PORT:-8000}..."
exec python -m uvicorn server:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1

