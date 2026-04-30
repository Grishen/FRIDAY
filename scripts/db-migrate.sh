#!/usr/bin/env bash
# Run migrations from repo root — same env wiring as scripts/run-api.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[db-migrate] Created .env from .env.example — edit DATABASE_* if needed, then re-run."
fi

cp "$ROOT/.env" "$ROOT/services/api/.env"

cd "$ROOT/services/api"
export PYTHONPATH="$ROOT/services/api/src"

echo "[db-migrate] PYTHONPATH=$PYTHONPATH"
exec alembic upgrade head
