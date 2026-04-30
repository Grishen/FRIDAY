# Phase 12 — Quality Gates (coverage, CI)

## API (`services/api`)

Run tests **from `services/api`** so `coverage` reads **`pyproject.toml`** (omit paths + `fail_under`):

```bash
./scripts/run-api-tests.sh
# or:
cd services/api && export PYTHONPATH=src && pytest tests --cov=friday_api --cov-report=term-missing --cov-config=pyproject.toml
```

- **`FRIDAY_PYTEST=1`** is set by `tests/conftest.py` before importing the app → async engine uses **`NullPool`** (avoids asyncpg concurrency issues under `TestClient`/httpx).
- **Excluded from coverage numerator** (intentionally out of scope here): websocket router, Celery `execute_tool_call` runner, **`workflow_service.py`** (large state-machine module with separate integration surface).
- **Gate**: **`fail_under = 83`** on the combined Coverage total line (statement + branches in this report). The script no longer overrides this with `--cov-fail-under=84`; run `pytest` from `services/api` so **`[tool.coverage.report]`** in `pyproject.toml` applies.

## Web (`apps/web`)

```bash
cd apps/web && npm run lint && npm run test -- --coverage && npm run build
```

Vitest thresholds are set in **`vitest.config.ts`** (focused on `src/lib/config.ts` initially).
