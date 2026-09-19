"""Convert memory and finding evidence IDs to UUID arrays.

Revision ID: 0011
Revises: 0010
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION prism_jsonb_to_uuid_array(value jsonb)
        RETURNS uuid[]
        LANGUAGE sql
        IMMUTABLE
        AS $$
            SELECT COALESCE(array_agg(item::uuid), ARRAY[]::uuid[])
            FROM jsonb_array_elements_text(value) AS item
        $$
        """
    )
    op.execute(
        """
        ALTER TABLE repository_memories
        ALTER COLUMN evidence_ids TYPE uuid[]
        USING prism_jsonb_to_uuid_array(evidence_ids)
        """
    )
    op.execute(
        """
        ALTER TABLE findings
        ALTER COLUMN evidence_ids TYPE uuid[]
        USING prism_jsonb_to_uuid_array(evidence_ids)
        """
    )
    op.execute("DROP FUNCTION prism_jsonb_to_uuid_array(jsonb)")


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE repository_memories
        ALTER COLUMN evidence_ids TYPE jsonb
        USING to_jsonb(evidence_ids)
        """
    )
    op.execute(
        """
        ALTER TABLE findings
        ALTER COLUMN evidence_ids TYPE jsonb
        USING to_jsonb(evidence_ids)
        """
    )
