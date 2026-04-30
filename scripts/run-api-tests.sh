#!/usr/bin/env bash
# Run pytest + coverage using services/api/pyproject.toml (must run inside services/api for omit/fail_under).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}/services/api"
export PYTHONPATH="${PWD}/src"
exec pytest tests -q --cov=friday_api --cov-report=term-missing "$@"
