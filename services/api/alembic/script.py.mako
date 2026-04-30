"""Alembic migration template."""

from alembic import op
import sqlalchemy as sa


revision = "${rev_id}"
down_revision = ${repr(down_revision) if down_revision else "None"}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
