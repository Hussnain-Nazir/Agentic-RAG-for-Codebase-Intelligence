import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.repository_index import RepositoryIndex


class RepositoryFileStatus(str, enum.Enum):
    OK = "OK"
    OVERSIZED = "OVERSIZED"
    BINARY = "BINARY"
    PARSE_FAILED = "PARSE_FAILED"


class RepositoryFile(Base):
    __tablename__ = "repository_files"
    __table_args__ = (
        UniqueConstraint(
            "repository_index_id",
            "path",
            name="uq_repository_files_index_path",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    repository_index_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("repository_indexes.id", ondelete="CASCADE"),
        nullable=False,
    )
    path: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str] = mapped_column(String(50), nullable=True)
    github_sha: Mapped[str] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=True)
    status: Mapped[RepositoryFileStatus] = mapped_column(
        Enum(RepositoryFileStatus, name="repository_file_status"),
        default=RepositoryFileStatus.OK,
        nullable=False,
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    repository_index: Mapped["RepositoryIndex"] = relationship(back_populates="files")
