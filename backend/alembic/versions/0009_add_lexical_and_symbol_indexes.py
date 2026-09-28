"""Add lexical search index.

Revision ID: 0009
Revises: 0008
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE code_chunks
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(content, ''))
        ) STORED
        """
    )
    op.execute(
        "CREATE INDEX ix_code_chunks_search_vector "
        "ON code_chunks USING gin (search_vector)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_code_chunks_search_vector")
    op.execute("ALTER TABLE code_chunks DROP COLUMN search_vector")
