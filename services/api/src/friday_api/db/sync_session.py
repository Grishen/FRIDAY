"""Synchronous sessions for Celery workers (async stack remains default for FastAPI)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from friday_api.config import get_settings

_settings = get_settings()
sync_engine = create_engine(
    _settings.sync_database_url,
    pool_pre_ping=True,
)
SyncSessionLocal = sessionmaker(bind=sync_engine)
