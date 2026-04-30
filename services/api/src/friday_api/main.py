"""FastAPI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from friday_tools import PolicyEngine, ToolGateway

from friday_api.config import get_settings
from friday_api.runtime import configure_gateway
from friday_api.telemetry import (
    otel_trace_context_processor,
    setup_observability_for_app,
    shutdown_tracer,
)
from friday_api.routers import (
    approvals,
    audit as audit_routes,
    auth_stub,
    documents as documents_routes,
    health,
    memory as memory_routes,
    meta as meta_routes,
    notifications as notifications_routes,
    sessions,
    smart_home as smart_home_routes,
    tools_rest,
    workflows as workflows_routes,
    ws,
)
from friday_api.tooling.bootstrap import build_default_registry

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        otel_trace_context_processor,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.JSONRenderer(),
    ]
)

logger = structlog.get_logger("friday.api")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> None:
    registry = build_default_registry()
    policy = PolicyEngine()
    gw = ToolGateway(registry, policy)
    configure_gateway(gw)
    logger.info("startup_complete", tools=len(registry.all_tools()))
    yield
    shutdown_tracer()
    logger.info("shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix=settings.api_prefix)
    app.include_router(meta_routes.router, prefix=settings.api_prefix)
    app.include_router(auth_stub.router, prefix=settings.api_prefix)
    app.include_router(sessions.router, prefix=settings.api_prefix)
    app.include_router(tools_rest.router, prefix=settings.api_prefix)
    app.include_router(memory_routes.router, prefix=settings.api_prefix)
    app.include_router(documents_routes.router, prefix=settings.api_prefix)
    app.include_router(approvals.router, prefix=settings.api_prefix)
    app.include_router(audit_routes.router, prefix=settings.api_prefix)
    app.include_router(workflows_routes.router, prefix=settings.api_prefix)
    app.include_router(notifications_routes.router, prefix=settings.api_prefix)
    app.include_router(smart_home_routes.router, prefix=settings.api_prefix)
    app.include_router(ws.router)
    setup_observability_for_app(app, settings)
    return app


app = create_app()


def dev() -> None:
    """Entry point for python -m friday_api."""
    import uvicorn

    uvicorn.run(
        "friday_api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    dev()
