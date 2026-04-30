"""OpenTelemetry SDK setup, FastAPI + SQLAlchemy + httpx instrumentation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from friday_api.config import Settings

_tracer_sdk_configured = False
_instrumented_engine_ids: set[int] = set()
_httpx_instrumented = False


def otel_trace_context_processor(
    _logger: object,
    _name: object,
    event_dict: dict[str, object],
) -> dict[str, object]:
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            event_dict["trace_id"] = f"{ctx.trace_id:032x}"
            event_dict["span_id"] = f"{ctx.span_id:016x}"
    except Exception:  # pragma: no cover - defensive only
        pass
    return event_dict


def reset_tracing_state_for_tests() -> None:
    """Tear down process-level instrumentation flags and SDK provider — tests only."""
    global _tracer_sdk_configured, _instrumented_engine_ids, _httpx_instrumented
    shutdown_tracer()
    _instrumented_engine_ids.clear()
    _httpx_instrumented = False
    try:
        from opentelemetry import trace
        from opentelemetry.trace import NoOpTracerProvider

        trace.set_tracer_provider(NoOpTracerProvider())
    except Exception:  # pragma: no cover
        pass


def shutdown_tracer() -> None:
    global _tracer_sdk_configured
    if not _tracer_sdk_configured:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider

        provider = trace.get_tracer_provider()
        if isinstance(provider, TracerProvider):
            provider.shutdown()
    finally:
        _tracer_sdk_configured = False


def _configure_tracer_provider(settings: Settings) -> None:
    global _tracer_sdk_configured
    if not settings.otel_effective_enabled:
        return
    if _tracer_sdk_configured:
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource_attrs: dict[str, str] = {
        "service.name": settings.resolved_otel_service_name(),
        "deployment.environment": settings.environment,
    }
    resource = Resource.create(resource_attrs)
    provider = TracerProvider(resource=resource)
    endpoint = settings.resolved_otlp_traces_http_endpoint()
    exporter = OTLPSpanExporter(endpoint=endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer_sdk_configured = True


def _instrument_sqlalchemy_engine(engine: object) -> None:
    eid = id(engine)
    if eid in _instrumented_engine_ids:
        return
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

    SQLAlchemyInstrumentor().instrument(engine=engine, enable_commenter=False)
    _instrumented_engine_ids.add(eid)


def _instrument_sqlalchemy_engines() -> None:
    from friday_api.db.session import engine as async_engine
    from friday_api.db.sync_session import sync_engine
    from friday_api.persistence.sync_db import _sync_engine

    _instrument_sqlalchemy_engine(async_engine.sync_engine)
    _instrument_sqlalchemy_engine(sync_engine)
    _instrument_sqlalchemy_engine(_sync_engine())


def _instrument_httpx() -> None:
    global _httpx_instrumented
    if _httpx_instrumented:
        return
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument()
    _httpx_instrumented = True


def _instrument_fastapi(app: FastAPI, settings: Settings) -> None:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    prefix = settings.api_prefix.strip("/")
    health = f"{prefix}/health" if prefix else "health"
    ready = f"{prefix}/ready" if prefix else "ready"
    excluded = f"/health,{health},/docs,/redoc,/openapi.json,{ready}"
    FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded)


def setup_observability_for_app(app: FastAPI, settings: Settings) -> None:
    """Configure OTLP trace export (if enabled) and instrument engines, httpx, and this app."""
    if not settings.otel_effective_enabled:
        return
    _configure_tracer_provider(settings)
    _instrument_sqlalchemy_engines()
    _instrument_httpx()
    _instrument_fastapi(app, settings)
