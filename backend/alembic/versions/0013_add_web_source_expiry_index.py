"""Index cached web-source expiry.

Revision ID: 0013
Revises: 0012
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_web_sources_retrieved_at", "web_sources", ["retrieved_at"])


def downgrade() -> None:
    op.drop_index("ix_web_sources_retrieved_at", table_name="web_sources")
