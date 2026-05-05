#!/usr/bin/env bash
# Run migrations from repo root — same env wiring philosophy as scripts/run-api.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[db-migrate] Created .env from .env.example — edit DATABASE_* if needed, then re-run."
fi

sync_from_root="${FRIDAY_SYNC_ROOT_ENV:-0}"
if [[ "${1:-}" == "--sync-env-from-root" ]]; then
  sync_from_root=1
  shift || true
fi

api_env="$ROOT/services/api/.env"
if [[ "${sync_from_root}" == "1" || ! -f "${api_env}" ]]; then
  cp "$ROOT/.env" "${api_env}"
  echo "[db-migrate] synced repo root .env → services/api/.env"
else
  echo "[db-migrate] using existing services/api/.env (not overwriting)."
fi

cd "$ROOT/services/api"
export PYTHONPATH="$ROOT/services/api/src"

echo "[db-migrate] PYTHONPATH=$PYTHONPATH"
exec alembic upgrade head
