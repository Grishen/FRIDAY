# Docker notes

The root `docker-compose.yml` provisions:

- `pgvector/pgvector:pg16` — Postgres on host port **`5433`** (maps to `5432` in the container; database `friday`, user/password `postgres`)
- `redis:7-alpine` on port `6379`
- `otel/opentelemetry-collector-contrib` (optional) — OTLP **gRPC `4317`**, HTTP **`4318`**, using `infra/docker/otel-collector-local.yaml` (debug exporter for local trace visibility)

Copy `.env.example` to `.env` at the repository root and align connection strings.

For production, split images per service, add TLS, configure Redis persistence, replace the collector’s debug exporter with your trace backend, and run Alembic from CI/CD before rolling new API revisions.
