"""Add trigram lookup for code symbol names.

Revision ID: 0006b
Revises: 0006
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0006b"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_code_symbols_name_trgm",
        "code_symbols",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_code_symbols_name_trgm", table_name="code_symbols")
