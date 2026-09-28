from typing import Literal

from app.github.client import GitHubClient
from app.ingestion.filtering import is_ignored_path, is_secret_file
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
        self._revisions_by_ref: dict[str, str] = {}
        self._prefetched_file: tuple[str, str, bytes] | None = None

    async def list_files(self, ref: str) -> list[SourceFileRef]:
        revision = await self.get_revision(ref)
        return await self.list_files_at_revision(ref, revision)

    async def list_files_at_revision(
        self, ref: str, revision: str
    ) -> list[SourceFileRef]:
        tree = await self._client.get_repository_tree(
            self._installation_id,
            self._repository_id,
            revision,
        )
        blobs: dict[str, str] = {}
        for item in tree:
            if item.get("type") != "blob":
                continue
            blobs[item["path"]] = item["sha"]
        patterns: list[str] = []
        if ".gitignore" in blobs:
            content = await self._client.get_blob_content(
                self._installation_id, self._repository_id, blobs[".gitignore"]
            )
            patterns = content.decode("utf-8", errors="replace").splitlines()
        files: list[SourceFileRef] = []
        for item in tree:
            if item.get("type") != "blob":
                continue
            path = item["path"]
            if is_ignored_path(path, patterns) or is_secret_file(path):
                continue
            files.append(
                SourceFileRef(
                    path=path,
                    size_bytes=int(item.get("size", 0)),
                    github_sha=item["sha"],
                )
            )
        self._blobs_by_ref[ref] = blobs
        self._revisions_by_ref[ref] = revision
        return sorted(files, key=lambda item: item.path)

    async def get_file_content(self, ref: str, path: str) -> bytes:
        if self._prefetched_file is not None and self._prefetched_file[:2] == (ref, path):
            content = self._prefetched_file[2]
            self._prefetched_file = None
            return content
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

    async def get_file_prefix(self, ref: str, path: str, max_bytes: int) -> bytes:
        if max_bytes < 0:
            raise ValueError("Prefix size must be non-negative")
        if ref not in self._blobs_by_ref:
            await self.list_files(ref)
        try:
            blob_sha = self._blobs_by_ref[ref][path]
        except KeyError as exc:
            raise FileNotFoundError(f"GitHub repository file was not found: {path}") from exc
        bounded_reader = getattr(self._client, "get_blob_prefix", None)
        if bounded_reader is not None:
            return await bounded_reader(
                self._installation_id, self._repository_id, blob_sha, max_bytes
            )
        content = await self.get_file_content(ref, path)
        self._prefetched_file = (ref, path, content)
        return content[:max_bytes]

    async def get_revision(self, ref: str) -> str:
        if ref in self._revisions_by_ref:
            return self._revisions_by_ref[ref]
        revision = await self._client.get_branch_revision(
            self._installation_id,
            self._repository_id,
            ref,
        )
        self._revisions_by_ref[ref] = revision
        return revision
