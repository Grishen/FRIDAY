"""Smart home stub device state overrides (Phase 11).

Revision ID: 20260430_0004
Revises: 20260429_0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "20260430_0004"
down_revision = "20260429_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "smart_home_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_key", sa.String(128), nullable=False),
        sa.Column("state", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "uq_smart_home_overrides_user_device",
        "smart_home_overrides",
        ["user_id", "device_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_smart_home_overrides_user_device", table_name="smart_home_overrides")
    op.drop_table("smart_home_overrides")
