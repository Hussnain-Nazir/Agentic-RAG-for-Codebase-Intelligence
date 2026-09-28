from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class SourceFileRef:
    path: str
    size_bytes: int
    github_sha: str | None = None


class RepositorySource(Protocol):
    source_type: Literal["github", "upload"]

    async def list_files(self, ref: str) -> list[SourceFileRef]: ...

    async def get_file_content(self, ref: str, path: str) -> bytes: ...

    async def get_file_prefix(self, ref: str, path: str, max_bytes: int) -> bytes: ...

    async def get_revision(self, ref: str) -> str: ...
