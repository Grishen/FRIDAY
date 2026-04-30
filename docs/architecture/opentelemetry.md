# OpenTelemetry (Phase 13)

The FRIDAY API can export **distributed traces** via **OTLP over HTTP** (protobuf) to any compatible collector or SaaS backend.

## What is instrumented

When tracing is enabled (`OTEL_ENABLED=true` and `OTEL_SDK_DISABLED` is unset/false), this process:

1. Registers an SDK **TracerProvider** with a **BatchSpanProcessor** and **OTLP HTTP span exporter**.
2. Instruments **FastAPI** (HTTP server spans; health, ready, docs, and OpenAPI paths are excluded from span creation to reduce noise).
3. Instruments **SQLAlchemy** for the async API engine (`engine.sync_engine`), the Celery-oriented sync engine (`sync_session.sync_engine`), and the dispatcher sync engine (`persistence.sync_db._sync_engine`).
4. Instruments outbound **httpx** clients.

Structured logs (structlog JSON) add **`trace_id`** and **`span_id`** when the OpenTelemetry context carries a valid span.

## Configuration

Environment variables (also see root **`.env.example`**):

| Variable | Role |
|----------|------|
| `OTEL_ENABLED` | `true` / `false` — master switch for this API process |
| `OTEL_SDK_DISABLED` | Standard OTel kill switch; when `true`/`1`/`yes`, tracing stays off even if `OTEL_ENABLED=true` |
| `OTEL_SERVICE_NAME` | `service.name` resource attribute (defaults to a slug of `app_name`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Base URL, e.g. `http://127.0.0.1:4318`; traces path `/v1/traces` is appended when missing |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` | Full traces URL, e.g. `http://127.0.0.1:4318/v1/traces` |

Default traces URL when neither endpoint is set: **`http://127.0.0.1:4318/v1/traces`**.

## Local collector

Root **`docker-compose.yml`** includes **`otel-collector`** (**`otel/opentelemetry-collector-contrib`**) with **`infra/docker/otel-collector-local.yaml`**, exposing:

- **4317** — OTLP gRPC
- **4318** — OTLP HTTP

The sample config uses the **debug** exporter so trace batches appear in the collector container logs (`docker compose logs -f otel-collector`).

Example:

```bash
docker compose up -d postgres redis otel-collector
export OTEL_ENABLED=true
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
./scripts/run-api.sh
```

## Meta endpoint

**`GET /api/v1/meta`** includes an **`observability`** object: whether tracing is active, exporter family (`none` | `otlp_http`), **`service_name`**, and sanitized OTLP **scheme** / **host[:port]** only (no credentials, no full path).

## Tests and CI

Automated tests leave **`OTEL_ENABLED`** off so no collector is required. Unit tests may call **`reset_tracing_state_for_tests()`** (`friday_api.telemetry`) after enabling OTEL in-process to avoid leaking global tracer state across cases.

## Celery workers

This phase focuses on the **HTTP API** process. Celery workers can be given the same env vars and optionally use **`opentelemetry-instrumentation-celery`** in a follow-up so task spans join the same trace context as the API.
