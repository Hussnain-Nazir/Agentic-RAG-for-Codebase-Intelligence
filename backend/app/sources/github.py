from typing import Literal

from app.sources.base import SourceFileRef


class GitHubRepositorySource:
    source_type: Literal["github"] = "github"

    async def list_files(self, ref: str) -> list[SourceFileRef]:
        raise NotImplementedError("GitHub repository file listing is not implemented")

    async def get_file_content(self, ref: str, path: str) -> bytes:
        raise NotImplementedError("GitHub repository file reading is not implemented")

    async def get_revision(self, ref: str) -> str:
        raise NotImplementedError("GitHub repository revision lookup is not implemented")
