"""Enable pgvector and add code chunks.

Revision ID: 0007
Revises: 0006
"""
from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

chunk_type = sa.Enum(
    "MODULE",
    "CLASS",
    "FUNCTION",
    "METHOD",
    "COMPONENT",
    "HOOK",
    "INTERFACE",
    "TYPE",
    "MODULE_SECTION",
    "DOCUMENTATION",
    "FALLBACK",
    name="code_chunk_type",
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "code_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("repository_index_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=50), nullable=False),
        sa.Column("chunk_type", chunk_type, nullable=False),
        sa.Column("symbol_name", sa.String(length=255), nullable=True),
        sa.Column("symbol_type", sa.String(length=50), nullable=True),
        sa.Column("parent_symbol", sa.String(length=255), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=384), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["file_id"], ["repository_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_index_id"], ["repository_indexes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_code_chunks_repository_index",
        "code_chunks",
        ["repository_id", "repository_index_id"],
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
    op.drop_index("ix_code_chunks_repository_index", table_name="code_chunks")
    op.drop_table("code_chunks")
    bind = op.get_bind()
    chunk_type.drop(bind, checkfirst=True)
