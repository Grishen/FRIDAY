"""Scheduled proactive rules — drive in-app notifications (Phase 10)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from friday_api.db.base import Base


class ProactiveRule(Base):
    """Simple interval-based scheduling (cron parser lands in a later phase)."""

    __tablename__ = "proactive_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(512))
    rule_type: Mapped[str] = mapped_column(String(64), index=True)
    interval_minutes: Mapped[int] = mapped_column(Integer(), default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean(), default=True)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
