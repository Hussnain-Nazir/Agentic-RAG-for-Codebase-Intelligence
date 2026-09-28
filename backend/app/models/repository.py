import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.code_chunk import CodeChunk
    from app.models.github_installation import GitHubInstallation
    from app.models.repository_index import RepositoryIndex
    from app.models.repository_memory import RepositoryMemory
    from app.models.finding import Finding
    from app.models.session import Session
    from app.models.user import User


class RepositorySourceType(str, enum.Enum):
    GITHUB = "github"
    UPLOAD = "upload"


class RepositoryAccessStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ACCESS_LOST = "ACCESS_LOST"
    SOURCE_DELETED = "SOURCE_DELETED"


class Repository(Base):
    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint(
            "github_installation_id",
            "github_repo_id",
            name="uq_repositories_installation_github_repo",
        ),
        Index("ix_repositories_owner_id", "owner_id"),
        Index("ix_repositories_github_repo_id", "github_repo_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    github_installation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("github_installations.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_type: Mapped[RepositorySourceType] = mapped_column(
        Enum(
            RepositorySourceType,
            name="repository_source_type",
            values_callable=lambda members: [member.value for member in members],
        ),
        nullable=False,
    )
    github_repo_id: Mapped[int] = mapped_column(BigInteger, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    default_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    selected_branch: Mapped[str] = mapped_column(String(255), nullable=False)
    access_status: Mapped[RepositoryAccessStatus] = mapped_column(
        Enum(RepositoryAccessStatus, name="repository_access_status"),
        default=RepositoryAccessStatus.ACTIVE,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    owner: Mapped["User"] = relationship(back_populates="repositories")
    github_installation: Mapped["GitHubInstallation"] = relationship(
        back_populates="repositories"
    )
    indexes: Mapped[list["RepositoryIndex"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    sessions: Mapped[list["Session"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    chunks: Mapped[list["CodeChunk"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    memories: Mapped[list["RepositoryMemory"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
