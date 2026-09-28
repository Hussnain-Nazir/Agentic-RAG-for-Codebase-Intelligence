"""Add repository memory, findings, and conversation messages.

Revision ID: 0010
Revises: 0009
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

memory_type = sa.Enum("FACT", "ARCHITECTURE", "CONVENTION", name="repository_memory_type")
memory_confidence = sa.Enum("high", "medium", "low", name="repository_memory_confidence")
memory_source = sa.Enum("AUTO", "EXPLICIT", name="repository_memory_source")
finding_type = sa.Enum("FLOW_TRACE", "IMPACT", "REVIEW", name="finding_type")
message_role = sa.Enum("user", "assistant", name="message_role")


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("role", message_role, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_session_id", "messages", ["session_id"])
    op.create_table(
        "repository_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("repository_index_version", sa.Integer(), nullable=False),
        sa.Column("type", memory_type, nullable=False),
        sa.Column("scope", sa.String(length=255), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("confidence", memory_confidence, nullable=False),
        sa.Column("is_stale", sa.Boolean(), nullable=False),
        sa.Column("source", memory_source, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_repository_memories_repository_stale",
        "repository_memories",
        ["repository_id", "is_stale"],
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("type", finding_type, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findings_repository_id", "findings", ["repository_id"])


def downgrade() -> None:
    op.drop_index("ix_findings_repository_id", table_name="findings")
    op.drop_table("findings")
    op.drop_index("ix_repository_memories_repository_stale", table_name="repository_memories")
    op.drop_table("repository_memories")
    op.drop_index("ix_messages_session_id", table_name="messages")
    op.drop_table("messages")
    bind = op.get_bind()
    finding_type.drop(bind, checkfirst=True)
    memory_source.drop(bind, checkfirst=True)
    memory_confidence.drop(bind, checkfirst=True)
    memory_type.drop(bind, checkfirst=True)
    message_role.drop(bind, checkfirst=True)
