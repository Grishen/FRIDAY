"""Application configuration."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import AliasChoices, Field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "FRIDAY API"
    environment: str = "development"
    api_prefix: str = "/api/v1"
    secret_key: str = "change-me-in-production"
    # Defaults align with `docker-compose.yml` (host 5433 → container 5432) and `.env.example`.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/friday"
    sync_database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5433/friday"
    redis_url: str = "redis://localhost:6379/0"
    embedding_dimensions: int = 1536
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    # LLM — OpenAI-compatible chat completions + streaming.
    openai_api_key: str = Field(default="", validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"))
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("OPENAI_BASE_URL", "openai_base_url"),
    )
    openai_chat_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("OPENAI_CHAT_MODEL", "openai_chat_model"),
    )
    llm_streaming: bool = Field(default=True, validation_alias=AliasChoices("LLM_STREAMING", "llm_streaming"))
    # Whisper / STT — multipart or WebSocket `voice.audio`; uses same OpenAI-compatible base URL + key.
    openai_whisper_model: str = Field(
        default="whisper-1",
        validation_alias=AliasChoices("OPENAI_WHISPER_MODEL", "openai_whisper_model"),
    )
    stt_max_upload_bytes: int = Field(
        default=5_242_880,
        validation_alias=AliasChoices("STT_MAX_UPLOAD_BYTES", "stt_max_upload_bytes"),
    )
    # OpenAI Realtime (WebRTC unified `/v1/realtime/calls`). Separate from orchestration/tool gateway today.
    openai_realtime_model: str = Field(
        default="gpt-realtime",
        validation_alias=AliasChoices("OPENAI_REALTIME_MODEL", "openai_realtime_model"),
    )
    openai_realtime_voice: str = Field(
        default="marin",
        validation_alias=AliasChoices("OPENAI_REALTIME_VOICE", "openai_realtime_voice"),
    )
    friday_realtime_instructions: str = Field(
        default=(
            "You are FRIDAY — the user's brisk, trustworthy voice copilot inside a Personal OS prototype. "
            "Keep replies concise unless asked for depth. You are speaking aloud; avoid markup."
        ),
        validation_alias=AliasChoices(
            "FRIDAY_REALTIME_INSTRUCTIONS",
            "friday_realtime_instructions",
        ),
    )
    # Governed host automation — sandboxed filesystem + allowlisted GUI apps only.
    friday_local_workspace: str = Field(
        default="",
        validation_alias=AliasChoices("FRIDAY_LOCAL_WORKSPACE", "friday_local_workspace"),
    )
    friday_open_app_allowlist: str = Field(
        default="",
        validation_alias=AliasChoices("FRIDAY_OPEN_APP_ALLOWLIST", "friday_open_app_allowlist"),
    )
    # OpenTelemetry — OTLP HTTP/protobuf to a collector or backend (Phase 13).
    otel_enabled: bool = Field(default=False, validation_alias=AliasChoices("OTEL_ENABLED", "otel_enabled"))
    otel_service_name: str = Field(default="", validation_alias=AliasChoices("OTEL_SERVICE_NAME", "otel_service_name"))
    otel_exporter_otlp_traces_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "otel_exporter_otlp_traces_endpoint"),
    )
    otel_exporter_otlp_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_ENDPOINT", "otel_exporter_otlp_endpoint"),
    )

    @property
    def otel_effective_enabled(self) -> bool:
        disabled = os.environ.get("OTEL_SDK_DISABLED", "").strip().lower()
        if disabled in ("true", "1", "yes"):
            return False
        return self.otel_enabled

    def resolved_otel_service_name(self) -> str:
        name = self.otel_service_name.strip()
        if name:
            return name
        return self.app_name.lower().replace(" ", "-").replace("_", "-")

    def resolved_otlp_traces_http_endpoint(self) -> str:
        """Full OTLP/HTTP traces URL (path /v1/traces)."""
        traces = self.otel_exporter_otlp_traces_endpoint
        if traces and traces.strip():
            return traces.strip().rstrip("/")
        general = self.otel_exporter_otlp_endpoint
        if general and general.strip():
            base = general.strip().rstrip("/")
            if base.endswith("/v1/traces"):
                return base
            return f"{base}/v1/traces"
        return "http://127.0.0.1:4318/v1/traces"


@lru_cache
def get_settings() -> Settings:
    return Settings()
