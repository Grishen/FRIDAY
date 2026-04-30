"""Developer / platform introspection endpoints (Phase 9)."""

from __future__ import annotations

import os
from functools import cache
from urllib.parse import urlparse

from fastapi import APIRouter, Response

from friday_api.config import get_settings
from friday_api.schemas.meta import ApiUrls, MetaOut, ObservabilityMeta, ReadyOut
from friday_api.services.ready_service import readiness_bundle

router = APIRouter(tags=["meta"])


@cache
def _package_version() -> str:
    try:
        from importlib.metadata import version

        return version("friday-api")
    except Exception:
        return "0.0.0"


def _observability_meta(settings_obj) -> ObservabilityMeta:
    name = settings_obj.resolved_otel_service_name()
    if not settings_obj.otel_effective_enabled:
        return ObservabilityMeta(
            tracing_enabled=False,
            exporter="none",
            service_name=name,
            otlp_traces_scheme=None,
            otlp_traces_host=None,
        )
    parsed = urlparse(settings_obj.resolved_otlp_traces_http_endpoint())
    host = parsed.hostname
    port = parsed.port
    if host is not None and port is not None:
        host_disp = f"{host}:{port}"
    else:
        host_disp = host
    return ObservabilityMeta(
        tracing_enabled=True,
        exporter="otlp_http",
        service_name=name,
        otlp_traces_scheme=parsed.scheme or None,
        otlp_traces_host=host_disp,
    )


@router.get("/meta", response_model=MetaOut)
async def api_meta() -> MetaOut:
    settings = get_settings()
    bid = (
        os.environ.get("FRIDAY_BUILD_ID")
        or os.environ.get("GIT_COMMIT_SHA")
        or os.environ.get("GITHUB_SHA")
        or os.environ.get("SOURCE_VERSION")
    )
    return MetaOut(
        service="friday-api",
        version=_package_version(),
        environment=settings.environment,
        build_id=bid.strip() if isinstance(bid, str) and bid.strip() else None,
        urls=ApiUrls(
            openapi_json="/openapi.json",
            swagger_ui="/docs",
            redoc="/redoc",
        ),
        observability=_observability_meta(settings),
    )


@router.get("/ready")
async def api_ready(response: Response) -> ReadyOut:
    """PostgreSQL connectivity is blocking; Redis issues mark the replica as degraded but keep HTTP 200."""
    db_res, redis_res = await readiness_bundle()

    db_ok, redis_ok = db_res["ok"], redis_res["ok"]
    out = ReadyOut(
        status="ready" if db_ok and redis_ok else "degraded",
        database=db_ok,
        redis=redis_ok,
        database_error=db_res["error"],
        redis_error=redis_res["error"],
    )

    if not db_ok:
        response.status_code = 503

    return out
