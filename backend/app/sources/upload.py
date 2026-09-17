from typing import Literal

from app.sources.base import SourceFileRef


class UploadedRepositorySource:
    source_type: Literal["upload"] = "upload"

    async def list_files(self, ref: str) -> list[SourceFileRef]:
        raise NotImplementedError("Uploaded repository file listing is not implemented")

    async def get_file_content(self, ref: str, path: str) -> bytes:
        raise NotImplementedError("Uploaded repository file reading is not implemented")

    async def get_revision(self, ref: str) -> str:
        raise NotImplementedError("Uploaded repository revision lookup is not implemented")
