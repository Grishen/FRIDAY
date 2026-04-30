"""Synchronous SQLAlchemy session for Celery workers (async API uses async engine)."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from friday_api.config import get_settings


@lru_cache(maxsize=1)
def _sync_engine():  # noqa: PLW0603 - single process-level sync pool for workers
    s = get_settings()
    return create_engine(s.sync_database_url, pool_pre_ping=True)


@contextmanager
def sync_session_scope() -> Iterator[Session]:
    Factory = sessionmaker(bind=_sync_engine(), expire_on_commit=False)
    sess = Factory()
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
