"""Add safe per-peer citation validation diagnostics.

Revision ID: 0015
Revises: 0014
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_executions", sa.Column("schema_validation_status", sa.String(64), nullable=True))
    op.add_column("model_executions", sa.Column("citation_total", sa.Integer(), nullable=True))
    op.add_column("model_executions", sa.Column("citation_accepted", sa.Integer(), nullable=True))
    op.add_column("model_executions", sa.Column("citation_rejected", sa.Integer(), nullable=True))
    op.add_column("model_executions", sa.Column(
        "citation_rejection_reasons", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True
    ))


def downgrade() -> None:
    op.drop_column("model_executions", "citation_rejection_reasons")
    op.drop_column("model_executions", "citation_rejected")
    op.drop_column("model_executions", "citation_accepted")
    op.drop_column("model_executions", "citation_total")
    op.drop_column("model_executions", "schema_validation_status")
