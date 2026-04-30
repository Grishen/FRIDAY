"""Proactive scheduling rules + notifications linkage (Phase 10).

Revision ID: 20260429_0003
Revises: 20260428_0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20260429_0003"
down_revision = "20260428_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proactive_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("rule_type", sa.String(64), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_fired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_proactive_rules_user_id", "proactive_rules", ["user_id"])
    op.create_index("ix_proactive_rules_rule_type", "proactive_rules", ["rule_type"])


def downgrade() -> None:
    op.drop_table("proactive_rules")
