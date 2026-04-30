"""Link tool calls to workflows for Phase 7 (pause on approval).

Revision ID: 20260428_0002
Revises: 20260427_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "20260428_0002"
down_revision = "20260427_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tool_calls",
        sa.Column("workflow_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tool_calls",
        sa.Column("workflow_step_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_tool_calls_workflow_id", "tool_calls", ["workflow_id"])
    op.create_foreign_key(
        "fk_tool_calls_workflow_id_workflows",
        "tool_calls",
        "workflows",
        ["workflow_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_tool_calls_workflow_step_id_workflow_steps",
        "tool_calls",
        "workflow_steps",
        ["workflow_step_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tool_calls_workflow_step_id_workflow_steps", "tool_calls", type_="foreignkey")
    op.drop_constraint("fk_tool_calls_workflow_id_workflows", "tool_calls", type_="foreignkey")
    op.drop_index("ix_tool_calls_workflow_id", table_name="tool_calls")
    op.drop_column("tool_calls", "workflow_step_id")
    op.drop_column("tool_calls", "workflow_id")
