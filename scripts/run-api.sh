#!/usr/bin/env bash
# Start the FastAPI server from repo root (one command — avoids paste/newline mistakes).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[run-api] Created .env from .env.example — edit DATABASE_* if needed, then re-run."
fi

cp "$ROOT/.env" "$ROOT/services/api/.env"

cd "$ROOT/services/api"
export PYTHONPATH="$ROOT/services/api/src"

echo "[run-api] PYTHONPATH=$PYTHONPATH"
exec uvicorn friday_api.main:app --reload --host 127.0.0.1 --port 8000
