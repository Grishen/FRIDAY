# FRIDAY Personal AI Operating System

Venture-grade **personal AI operating layer** — not a lone chat widget. Voice, text, files, memory, tools, workflows, approvals, audits, and provider abstractions compose into a cohesive platform you can extend service-by-service.

## Monorepo map

| Path | Description |
|------|-------------|
| `apps/web` | Next.js shell: assistant console, voice UX placeholders, integrations & workflow pages |
| `apps/desktop` | Electron window embedding `apps/web` (Phase 8 — `FRIDAY_WEB_URL`, preload bridge) |
| `services/api` | FastAPI orchestration — REST + WebSocket, SQLAlchemy models, Alembic, optional OpenTelemetry (Phase 13) |
| `services/agent` | Intent routing, planning, responder, specialized agent skeletons |
| `services/memory` | Memory contracts (profile/episodic/semantic/task) — persistence in API DB |
| `services/tools` | Tool registry, policy engine hooks, synchronous gateway executor |
| `services/audit` | Audit event schemas + adapters |
| `services/workflow` | Workflow transition rules |
| `services/notifications` | Notification payloads + dispatcher seam |
| `packages/shared-types` | Shared TypeScript contracts (expand with OpenAPI codegen) |
| `packages/policy-engine` | Shared risk/policy helpers for UI + backend symmetry |
| `docs/` | Phase-0 architecture, security, roadmap · **`docs/api/openapi.json`** (Phase **9**) |
| `docker-compose.yml` | Postgres (+pgvector), Redis, optional OpenTelemetry collector (OTLP 4317/4318) |

## Quick start

### Prerequisites

- Python ≥ 3.12 (3.14 tested)
- Node 20+/npm
- Docker (optional — for Postgres + Redis locally)

### Python services

Use a **`.env` file**. Pydantic loads `services/api/.env` when the process cwd is `services/api`.

```bash
pip install -r requirements-python.txt
./scripts/db-migrate.sh
./scripts/run-api.sh
```

**Migrations:** `db-migrate.sh` copies the repo `.env` into `services/api/.env`, sets `PYTHONPATH`, and runs `alembic upgrade head`. Alternative: `( cd services/api && PYTHONPATH=src alembic upgrade head )`, or — with the repo-root `alembic.ini` — `alembic upgrade head` from the repository root (`FRIDAY`). Running **`alembic` from the repo root without that file** yields `No 'script_location' key found in configuration`; use the script or stay inside `services/api` with its local `alembic.ini`.

`run-api.sh` also syncs `.env` into `services/api/` and starts uvicorn. Type pip / migrate / run-api as **separate commands** or real newlines — pasting **`pip … ( cd …`** on one line (no newline before `(` ) turns into garbage like `requirements-python.txt(`.


If you use **Fish**, run `./scripts/run-api.sh` from the repo root (the script is bash; your shell only invokes it).


Bootstrap a dev identity then create sessions with header `X-User-Id`:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/bootstrap -H 'Content-Type: application/json' -d '{}'
```

### Web shell

```bash
cd apps/web
cp ../../.env.example .env.local   # NEXT_PUBLIC_API_URL should match `./scripts/run-api.sh` (default http://127.0.0.1:8000)
npm install
npm run dev
```

If you still see **`Failed to fetch`** on bootstrap, rebuild after changing **`NEXT_PUBLIC_API_***`**, ensure the API is reachable at that URL, and set **`CORS_ORIGINS`** (repo `.env`) to include both **`http://localhost:3000`** and **`http://127.0.0.1:3000`** (Electron uses the latter).

### Docker data stores

```bash
docker compose up -d
```

If `docker compose` fails on credential helpers, ensure Docker Desktop is healthy or run Postgres/Redis manually with the same connection strings as `.env.example`.

## Phase 2 — Voice UX

Browser **Web Speech API** transcription + **Hold-to-talk** + **WebSocket** assistant phases (`checking_calendar`, `reading_documents`, `waiting_approval`, `synthesizing_response`, …) emitted server-side during `run_turn`.

## Phase 3 — Memory

Long-term memories on Postgres + **`pgvector`**: **`/api/v1/memory`** CRUD + **`POST .../memory/search`**. Web: **`/memory`**. Add **HNSW / IVFFLAT** on `memories.embedding` at scale.

## Personal OS mode (optional)

Set **`OPENAI_API_KEY`** (+ optional **`OPENAI_BASE_URL`**, **`OPENAI_CHAT_MODEL`**) so turns use **streaming** OpenAI-compatible completions over WebSocket (`assistant.delta`). Without a key, completions stay on the mock provider for offline dev.

Use **`FRIDAY_LOCAL_WORKSPACE`** plus **`FRIDAY_OPEN_APP_ALLOWLIST`** to enable **sandboxed** filesystem tools and **allowlisted GUI app** open/quit flows (writes and app control require **approval** like other high-risk tools; run Celery worker on the same host when approving those actions).

See **`.env.example`** for placeholders.

Multipart **`POST /api/v1/documents/upload`** (UTF-8 text) → chunk (**`text_chunking`**) → **mock embeddings** stored on **`document_chunks.embedding`**. **`POST /api/v1/documents/query`** runs pgvector similarity + **citations**. Tool **`documents.ask`** uses the same RAG backend (gateway passes **`user_id`** into handlers). Web: **`/documents`**.

## Phase 5 — Planner & context

**`IntentRouter`** → **`PlannerAgent`** (**registry-scoped tools**) + **`load_turn_context_bundle`** (transcript + memory **`pgvector`** + tool catalog). See `services/agent`, **`orchestration.py`**, **`turn_context.py`**.

## Phase 4 — Tools & approvals

**`PolicyEngine`** + **`ToolGateway`** (`services/tools`) serve mock tools at API startup. High-risk tools (`email.send`) return **`pending_approval`** → `Approval` + `ToolCall`; **`POST /api/v1/approvals/{id}/resolve`** writes audit and, on approve, enqueues **Celery**. **`GET /api/v1/audit`** lists events; **`/debug`** in the web app shows recent rows.

Tip: include **send** in the user message so the planner picks **`email.send`** and the WebSocket emits **`waiting_approval`** with a real `approval_id`.

## Celery worker (post-approval execution)

Approvals are resolved over REST; **approved** high-risk tool runs are executed by a Celery worker so the API stays responsive and retries can be added later.

Requirements: Redis reachable at `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` (see `.env.example`).

```bash
./scripts/run_celery_worker.sh
```

Ensure `PYTHONPATH` points at `services/api/src` (the script sets this) and Redis is running (`docker compose up -d redis`).

Optional **beat** (scheduled tasks): proactive notification ticks run **`friday.tasks.proactive_tick`** every **5 minutes** when beat is active.

```bash
./scripts/run_celery_beat.sh
```

Run beat in a separate terminal alongside the worker.

## Tests

```bash
./scripts/run-api-tests.sh
cd apps/web && npm run lint && npm run test -- --coverage && npm run build
```

Postgres migrated (`./scripts/db-migrate.sh`) is required for API integration coverage. **`docs/testing/phase12-quality.md`** documents gates and exclusions.

## Architecture docs

- `docs/testing/phase12-quality.md`
- `docs/architecture/overview.md`
- `docs/product/vision.md`
- `docs/security/approval-matrix.md`
- `docs/api/rest.md`

## Roadmap snapshot

Phases **1–8** span RAG … **Desktop** (`apps/desktop`). **Phase 9** adds the **developer platform** (`GET /meta`, `GET /ready`, `docs/api/openapi.json`, web **`/dev`**); **Phase 10** adds **`/notifications`**, proactive rules, dispatch + Celery beat; **Phase 11** adds stub **smart home** REST + planner tools + **`/integrations`**. **Phase 12** adds **`./scripts/run-api-tests.sh`**, coverage gates (**`services/api/pyproject.toml`**), **`apps/web`** Vitest smoke, GitHub Actions (`.github/workflows/ci.yml`). **Phase 13** tracks OpenTelemetry exporters. See `docs/architecture/roadmap.md`.

### Phase 8 — Desktop shell

```bash
cd apps/desktop && npm install && npm run dev
```

Starts Electron pointed at **`http://127.0.0.1:3000`** — run **`npm run dev`** in **`apps/web`** first, or set **`FRIDAY_WEB_URL`** to your UI origin. Details: **`apps/desktop/README.md`**.

### Phase 9 — Developer platform

Web: **`apps/web`** → **`/dev`** shows **`GET /api/v1/meta`**, **`GET /api/v1/ready`**, links to Swagger / OpenAPI. Regenerate **`docs/api/openapi.json`** (no running server):

```bash
PYTHONPATH=services/api/src python scripts/export-openapi.py
```

### Phase 10 — Notifications & proactive rules

REST: **`GET /api/v1/notifications`**, **`POST /api/v1/notifications/{id}/ack`**, **`GET` / **`POST`** / **`PATCH`** under **`…/notifications/rules`**, **`POST …/notifications/dispatch`**. Web: **`apps/web`** → **`/notifications`** (dev **`X-User-Id`** from bootstrap). Scheduled fan-out uses Celery (**`./scripts/run_celery_beat.sh`** + **`./scripts/run_celery_worker.sh`**).

### Phase 11 — Smart home stubs

Migrate DB (**includes `smart_home_overrides`**), then use **`GET/PATCH …/smart-home/devices`**, **`smarthome.list_devices`** / **`smarthome.set_device_state`** tools, web **`apps/web`** → **`/integrations`**.

### Phase 12 — Coverage + CI

Quality gates (**≥84%** Coverage total on **`friday_api`** with documented omits — see **`services/api/pyproject.toml`**), `./scripts/run-api-tests.sh`, `apps/web` Vitest smoke on **`normalizeLocalApiOrigin`**, **`/.github/workflows/ci.yml`** (Postgres/pgvector + Redis services, migrations).

## License

Proprietary / set your license.
