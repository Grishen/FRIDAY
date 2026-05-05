#!/usr/bin/env bash
# Start the FastAPI server from repo root (one command — avoids paste/newline mistakes).
#
# Secrets for the API normally live in `services/api/.env` (the process cwd reads that file).
#
# Repo root `.env` is still created from `.env.example` for DATABASE_* parity, but it is ONLY
# copied into `services/api/.env` when that file does not exist yet, unless you explicitly sync:
#   FRIDAY_SYNC_ROOT_ENV=1 ./scripts/run-api.sh
# or:
#   ./scripts/run-api.sh --sync-env-from-root
#
# That avoids the footgun where you edit `services/api/.env`, run `./scripts/run-api.sh`, and
# the copy step wipes your changes (e.g. a new OPENAI_API_KEY).

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[run-api] Created .env from .env.example — edit DATABASE_* if needed, then re-run."
fi

sync_from_root="${FRIDAY_SYNC_ROOT_ENV:-0}"
if [[ "${1:-}" == "--sync-env-from-root" ]]; then
  sync_from_root=1
  shift || true
fi

api_env="$ROOT/services/api/.env"
if [[ "${sync_from_root}" == "1" || ! -f "${api_env}" ]]; then
  cp "$ROOT/.env" "${api_env}"
  echo "[run-api] synced repo root .env → services/api/.env"
else
  echo "[run-api] using existing services/api/.env (not overwriting). To copy repo root → API: FRIDAY_SYNC_ROOT_ENV=1 $0 OR $0 --sync-env-from-root"
fi

cd "$ROOT/services/api"
export PYTHONPATH="$ROOT/services/api/src"

echo "[run-api] PYTHONPATH=$PYTHONPATH"
exec uvicorn friday_api.main:app --reload --host 127.0.0.1 --port 8000 "$@"
