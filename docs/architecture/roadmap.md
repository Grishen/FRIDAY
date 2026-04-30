# Delivery Roadmap (Phased)

| Phase | Scope | Exit criteria |
|-------|--------|----------------|
| 0 | Product + architecture docs | Docs merged, vision aligned |
| 1 | Monorepo, FastAPI, Next.js, DB models, WebSocket chat, providers | Compose up, demo chat persists |
| 2 | Voice UX, statuses, streaming hooks | Push-to-talk + status pipeline (mock audio) |
| 3 | Memory service + pgvector + settings UI | **Done:** CRUD + SQL cosine search + `/memory` UI |
| 4 | Tool gateway, policy engine, approvals, mocks, audit | **Done:** Gateway + resolve + Celery + audit API + UI |
| 5 | Intent router + planner + context + agents | **Done:** Intent→plan scoped to registry; transcript + pgvector memory + tools in context |
| 6 | Upload, chunk, embed, RAG API, citations | **Done:** Multipart ingest + `/documents/query` + tool `documents.ask` + `/documents` UI |
| 7 | Workflow engine + briefing / meeting prep | **Done:** templates + `/workflows` API; tool steps pause on approval; resolve advances workflow |
| 8 | Desktop shell (Electron) embeds web console | `apps/desktop`; `FRIDAY_WEB_URL`; preload `fridayDesktop` |
| **9** | **Developer platform** · readiness · meta · OpenAPI artifact | **`GET /api/v1/meta`**, **`GET /api/v1/ready`**, `docs/api/openapi.json`, web **`/dev`** |
| **10** | Notifications + proactive rules | **`GET/PATCH …/notifications`**, rules CRUD + **`POST …/dispatch`**, Celery beat + worker |
| **11** | Smart home stubs | **`GET/PATCH …/smart-home/devices`**, Postgres overrides, tools **`smarthome.*`**, web **`/integrations`** |
| **12** | Hardened tests + gates + CI | **pytest + coverage gate** (`services/api/pyproject.toml`); async HTTP fixtures; `./scripts/run-api-tests.sh`; GitHub Actions CI; Vitest on `src/lib/config.ts`; smoke checks vs `openapi.json`; see `docs/testing/phase12-quality.md` |
| **13** | Observability exporters | **Done:** OTLP HTTP tracing (FastAPI + SQLAlchemy + httpx), local `otel-collector` in Compose, `GET /api/v1/meta.observability`, `docs/architecture/opentelemetry.md` |

## 30-Day Target (from kickoff)

- **Week 1:** Monorepo, backend, frontend shell, DB, WebSocket chat.
- **Week 2:** Memory + embeddings + voice UI + settings.
- **Week 3:** Tool gateway, approvals, calendar/email/task **mock** tools.
- **Week 4:** Planner, workflows skeleton, RAG path, daily briefing demo.
