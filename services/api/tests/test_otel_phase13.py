"""OpenTelemetry configuration and wiring (Phase 13)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from friday_api.config import Settings, get_settings
from friday_api.main import create_app
from friday_api.routers import meta as meta_routes
from friday_api.telemetry import reset_tracing_state_for_tests
from friday_api.telemetry import otel as otel_mod


def test_observability_meta_builds_hints_for_enabled_tracing() -> None:
    s = Settings(otel_enabled=True, otel_exporter_otlp_endpoint="https://collector.example:4318")
    out = meta_routes._observability_meta(s)
    assert out.tracing_enabled is True
    assert out.exporter == "otlp_http"
    assert out.otlp_traces_scheme == "https"
    assert out.otlp_traces_host == "collector.example:4318"


def test_observability_meta_no_host_when_url_has_no_netloc() -> None:
    s = Settings(otel_enabled=True, otel_exporter_otlp_traces_endpoint="/v1/traces")
    out = meta_routes._observability_meta(s)
    assert out.otlp_traces_host is None


    s = Settings(
        otel_exporter_otlp_traces_endpoint="http://collector:4318/v1/traces",
    )
    assert s.resolved_otlp_traces_http_endpoint() == "http://collector:4318/v1/traces"


def test_resolved_otlp_traces_from_base_endpoint() -> None:
    s = Settings(
        otel_exporter_otlp_endpoint="http://collector:4318",
    )
    assert s.resolved_otlp_traces_http_endpoint() == "http://collector:4318/v1/traces"


def test_resolved_service_name_default() -> None:
    s = Settings()
    assert s.resolved_otel_service_name() == "friday-api"


def test_otel_effective_disabled_with_sdk_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    s = Settings(otel_enabled=True)
    assert s.otel_effective_enabled is False


def test_configure_tracing_calls_otlp_exporter() -> None:
    reset_tracing_state_for_tests()
    s = Settings(otel_enabled=True)
    assert s.otel_effective_enabled is True
    with patch(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
        autospec=True,
    ) as exp_cls:
        exp_cls.return_value = MagicMock()
        otel_mod._configure_tracer_provider(s)  # noqa: SLF001
        exp_cls.assert_called_once()
    reset_tracing_state_for_tests()


def test_setup_observability_idempotent_engines(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_tracing_state_for_tests()
    get_settings.cache_clear()
    monkeypatch.setenv("OTEL_ENABLED", "true")
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    with (
        patch(
            "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter",
            autospec=True,
        ) as exp_cls,
        patch(
            "opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor",
            autospec=True,
        ) as sa_cls,
        patch(
            "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor",
            autospec=True,
        ) as hx_cls,
        patch(
            "opentelemetry.instrumentation.fastapi.FastAPIInstrumentor",
            autospec=True,
        ) as fa_cls,
    ):
        exp_cls.return_value = MagicMock()
        sa_inst = MagicMock()
        sa_cls.return_value = sa_inst
        hx_inst = MagicMock()
        hx_cls.return_value = hx_inst
        app1 = create_app()
        app2 = create_app()
        assert app1 is not app2
        assert sa_inst.instrument.call_count == 3  # three distinct engines, once each
        hx_inst.instrument.assert_called_once()
        assert fa_cls.instrument_app.call_count == 2
    reset_tracing_state_for_tests()
    get_settings.cache_clear()


def test_otel_trace_context_processor_skips_without_span() -> None:
    ev = {"event": "x"}
    assert otel_mod.otel_trace_context_processor(None, None, ev) == ev
