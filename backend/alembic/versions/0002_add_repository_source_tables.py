"""Add repository source tables.

Revision ID: 0002
Revises: 0001
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

github_installation_status = sa.Enum(
    "ACTIVE",
    "REVOKED",
    name="github_installation_status",
)
repository_source_type = sa.Enum(
    "github",
    "upload",
    name="repository_source_type",
)
repository_access_status = sa.Enum(
    "ACTIVE",
    "ACCESS_LOST",
    "SOURCE_DELETED",
    name="repository_access_status",
)
repository_index_state = sa.Enum(
    "PENDING",
    "DISCOVERING",
    "PARSING",
    "EMBEDDING",
    "INDEXING",
    "READY",
    "FAILED",
    "PARTIAL",
    name="repository_index_state",
)
repository_file_status = sa.Enum(
    "OK",
    "OVERSIZED",
    "BINARY",
    "PARSE_FAILED",
    name="repository_file_status",
)


def upgrade() -> None:
    op.create_table(
        "github_installations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("account_login", sa.String(length=255), nullable=False),
        sa.Column("status", github_installation_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_id"),
    )
    op.create_table(
        "repositories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("github_installation_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", repository_source_type, nullable=False),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("default_branch", sa.String(length=255), nullable=False),
        sa.Column("selected_branch", sa.String(length=255), nullable=False),
        sa.Column("access_status", repository_access_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["github_installation_id"],
            ["github_installations.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "github_installation_id",
            "github_repo_id",
            name="uq_repositories_installation_github_repo",
        ),
    )
    op.create_index("ix_repositories_owner_id", "repositories", ["owner_id"])
    op.create_index(
        "ix_repositories_github_repo_id",
        "repositories",
        ["github_repo_id"],
    )
    op.create_table(
        "repository_indexes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.String(length=255), nullable=False),
        sa.Column("state", repository_index_state, nullable=False),
        sa.Column("files_discovered", sa.Integer(), nullable=False),
        sa.Column("files_processed", sa.Integer(), nullable=False),
        sa.Column("files_failed", sa.Integer(), nullable=False),
        sa.Column("failure_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["repository_id"],
            ["repositories.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_id",
            "version",
            name="uq_repository_indexes_repository_version",
        ),
    )
    op.create_table(
        "repository_files",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("repository_index_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("github_sha", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("status", repository_file_status, nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["repository_index_id"],
            ["repository_indexes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "repository_index_id",
            "path",
            name="uq_repository_files_index_path",
        ),
    )


def downgrade() -> None:
    op.drop_table("repository_files")
    op.drop_table("repository_indexes")
    op.drop_index("ix_repositories_github_repo_id", table_name="repositories")
    op.drop_index("ix_repositories_owner_id", table_name="repositories")
    op.drop_table("repositories")
    op.drop_table("github_installations")

    bind = op.get_bind()
    repository_file_status.drop(bind, checkfirst=True)
    repository_index_state.drop(bind, checkfirst=True)
    repository_access_status.drop(bind, checkfirst=True)
    repository_source_type.drop(bind, checkfirst=True)
    github_installation_status.drop(bind, checkfirst=True)
