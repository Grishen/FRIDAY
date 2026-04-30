"""Initial schema creation.

Revision ID: 20260427_0001
"""

from __future__ import annotations

from alembic import op


revision = "20260427_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "vector";')

    bind = op.get_bind()
    from friday_api.db.base import Base
    import friday_api.models  # noqa: F401

    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    from friday_api.db.base import Base
    import friday_api.models  # noqa: F401

    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
