"""Add cached web search sources.

Revision ID: 0012
Revises: 0011
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "web_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("source_domain", sa.String(length=255), nullable=False),
        sa.Column(
            "retrieved_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_hash", "url", name="uq_web_sources_query_url"),
    )
    op.create_index(
        "ix_web_sources_query_hash", "web_sources", ["query_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_web_sources_query_hash", table_name="web_sources")
    op.drop_table("web_sources")
