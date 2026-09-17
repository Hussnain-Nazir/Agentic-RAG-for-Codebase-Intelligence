from typing import Literal

from app.github.client import GitHubClient
from app.sources.base import SourceFileRef


class GitHubRepositorySource:
    source_type: Literal["github"] = "github"

    def __init__(
        self,
        client: GitHubClient,
        installation_id: int,
        repository_id: int,
    ) -> None:
        self._client = client
        self._installation_id = installation_id
        self._repository_id = repository_id
        self._blobs_by_ref: dict[str, dict[str, str]] = {}

    async def list_files(self, ref: str) -> list[SourceFileRef]:
        revision = await self.get_revision(ref)
        tree = await self._client.get_repository_tree(
            self._installation_id,
            self._repository_id,
            revision,
        )
        blobs: dict[str, str] = {}
        files: list[SourceFileRef] = []
        for item in tree:
            if item.get("type") != "blob":
                continue
            path = item["path"]
            sha = item["sha"]
            blobs[path] = sha
            files.append(
                SourceFileRef(
                    path=path,
                    size_bytes=int(item.get("size", 0)),
                    github_sha=sha,
                )
            )
        self._blobs_by_ref[ref] = blobs
        return sorted(files, key=lambda item: item.path)

    async def get_file_content(self, ref: str, path: str) -> bytes:
        if ref not in self._blobs_by_ref:
            await self.list_files(ref)
        try:
            blob_sha = self._blobs_by_ref[ref][path]
        except KeyError as exc:
            raise FileNotFoundError(f"GitHub repository file was not found: {path}") from exc
        return await self._client.get_blob_content(
            self._installation_id,
            self._repository_id,
            blob_sha,
        )

    async def get_revision(self, ref: str) -> str:
        return await self._client.get_branch_revision(
            self._installation_id,
            self._repository_id,
            ref,
        )
