"""Track embedding versions and add vector search indexes.

Revision ID: 0008
Revises: 0007
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "code_chunks",
        sa.Column("embedding_model_version", sa.String(length=255), nullable=True),
    )
    # Phase 8 briefly created these Phase 9 indexes. Dropping conditionally keeps
    # upgrades safe for databases that applied that earlier migration version.
    op.execute("DROP INDEX IF EXISTS ix_code_chunks_embedding_cosine")
    op.execute("DROP INDEX IF EXISTS ix_code_chunks_repository_index")
    op.create_index(
        "ix_code_chunks_repository_index",
        "code_chunks",
        ["repository_id", "repository_index_id"],
    )
    op.create_index(
        "ix_code_chunks_content_embedding_version",
        "code_chunks",
        ["content_hash", "embedding_model_version"],
    )
    op.create_index(
        "ix_code_chunks_embedding_cosine",
        "code_chunks",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"lists": 100},
    )


def downgrade() -> None:
    op.drop_index("ix_code_chunks_embedding_cosine", table_name="code_chunks")
    op.drop_index(
        "ix_code_chunks_content_embedding_version", table_name="code_chunks"
    )
    op.drop_index("ix_code_chunks_repository_index", table_name="code_chunks")
    op.drop_column("code_chunks", "embedding_model_version")
