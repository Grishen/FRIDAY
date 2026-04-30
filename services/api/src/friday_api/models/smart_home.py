"""User-scoped smart home stub overrides (Phase 11)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from friday_api.db.base import Base


class SmartHomeDeviceOverride(Base):
    """Merged device state persisted per stub device key."""

    __tablename__ = "smart_home_overrides"
    __table_args__ = (UniqueConstraint("user_id", "device_key", name="uq_smart_home_overrides_user_device"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_key: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
