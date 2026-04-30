#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="${ROOT}/services/api/src"
exec celery -A friday_api.celery_app:celery_app beat --loglevel=info
