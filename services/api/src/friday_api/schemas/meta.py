"""Build metadata & readiness payloads (Phase 9)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ApiUrls(BaseModel):
    openapi_json: str = Field(description="OpenAPI schema (machine-readable)")
    swagger_ui: str = Field(description="Swagger UI")
    redoc: str = Field(description="ReDoc")


class ObservabilityMeta(BaseModel):
    """Non-secret tracing hints for operators (Phase 13 — OpenTelemetry)."""

    tracing_enabled: bool = Field(description="Whether OTLP HTTP trace export is active in this process")
    exporter: Literal["none", "otlp_http"] = Field(description="Active trace exporter")
    service_name: str = Field(description="OpenTelemetry resource attribute service.name")
    otlp_traces_scheme: str | None = Field(default=None, description="URL scheme for traces export (sanitized)")
    otlp_traces_host: str | None = Field(
        default=None,
        description="Host (and optional port) for OTLP traces URL — no paths or secrets",
    )


class MetaOut(BaseModel):
    service: str
    version: str
    environment: str
    build_id: str | None = None
    urls: ApiUrls
    observability: ObservabilityMeta


class ReadyOut(BaseModel):
    status: Literal["ready", "degraded"]
    database: bool
    redis: bool
    database_error: str | None = None
    redis_error: str | None = None
