#!/usr/bin/env bash
# Start local pheonix API (:8000) and Vite UI (:5173) in the background.
# Prefer running this (or `make api` / `make ui`) in YOUR terminal so processes
# outlive agent shells. See also: `make stack`.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_LOG="$ROOT/backend/logs/api.nohup.out"
UI_LOG="$ROOT/frontend/logs/ui.nohup.out"
mkdir -p "$ROOT/backend/logs" "$ROOT/frontend/logs"

api_up() { curl -fsS --connect-timeout 1 "http://127.0.0.1:8000/health" >/dev/null 2>&1; }
ui_up() { curl -fsS --connect-timeout 1 "http://localhost:5173/" >/dev/null 2>&1; }

if api_up; then
  echo "API already up on http://127.0.0.1:8000"
else
  echo "Starting API on :8000 ..."
  (
    cd "$ROOT/backend"
    nohup env PHEONIX_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173 \
      .venv/bin/uvicorn --factory phoenix_scraper.api:create_app_default \
      --host 127.0.0.1 --port 8000 \
      >"$API_LOG" 2>&1 </dev/null &
    disown || true
  )
  for _ in $(seq 1 20); do api_up && break; sleep 0.25; done
  api_up || { echo "API failed to start; see $API_LOG"; exit 1; }
  echo "API ready → http://127.0.0.1:8000 (log: $API_LOG)"
fi

if ui_up; then
  echo "UI already up on http://localhost:5173"
else
  echo "Starting UI on :5173 ..."
  (
    cd "$ROOT/frontend"
    nohup npm run dev >"$UI_LOG" 2>&1 </dev/null &
    disown || true
  )
  for _ in $(seq 1 40); do ui_up && break; sleep 0.25; done
  ui_up || { echo "UI failed to start; see $UI_LOG"; exit 1; }
  echo "UI ready → http://localhost:5173 (log: $UI_LOG)"
fi

echo
echo "Open http://localhost:5173/ — API CORS is set for that origin."
echo "Stop later with: lsof -tiTCP:8000,5173 -sTCP:LISTEN | xargs kill"
