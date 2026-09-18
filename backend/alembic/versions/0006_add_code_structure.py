"""Add persisted source content, code symbols, and relationships.

Revision ID: 0006
Revises: 0005
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

relationship_kind = sa.Enum(
    "CALLS",
    "IMPORTS",
    "REFERENCES",
    "API_CALL",
    "EXTENDS",
    name="code_relationship_kind",
)
relationship_confidence = sa.Enum(
    "high",
    "low",
    name="code_relationship_confidence",
)


def upgrade() -> None:
    op.add_column("repository_files", sa.Column("content", sa.Text(), nullable=True))
    op.create_table(
        "code_symbols",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_index_id", sa.Uuid(), nullable=False),
        sa.Column("file_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("symbol_type", sa.String(length=50), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("parent_symbol", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["repository_files.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_index_id"], ["repository_indexes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_code_symbols_index_name",
        "code_symbols",
        ["repository_index_id", "name"],
    )
    op.create_table(
        "code_relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_index_id", sa.Uuid(), nullable=False),
        sa.Column("from_symbol_id", sa.Uuid(), nullable=False),
        sa.Column("to_symbol_id", sa.Uuid(), nullable=True),
        sa.Column("kind", relationship_kind, nullable=False),
        sa.Column("confidence", relationship_confidence, nullable=False),
        sa.ForeignKeyConstraint(["from_symbol_id"], ["code_symbols.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["repository_index_id"], ["repository_indexes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_symbol_id"], ["code_symbols.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_code_relationships_from_symbol_id",
        "code_relationships",
        ["from_symbol_id"],
    )
    op.create_index(
        "ix_code_relationships_to_symbol_id",
        "code_relationships",
        ["to_symbol_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_code_relationships_to_symbol_id", table_name="code_relationships")
    op.drop_index("ix_code_relationships_from_symbol_id", table_name="code_relationships")
    op.drop_table("code_relationships")
    op.drop_index("ix_code_symbols_index_name", table_name="code_symbols")
    op.drop_table("code_symbols")
    op.drop_column("repository_files", "content")

    bind = op.get_bind()
    relationship_confidence.drop(bind, checkfirst=True)
    relationship_kind.drop(bind, checkfirst=True)
