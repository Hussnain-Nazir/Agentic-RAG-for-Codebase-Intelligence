import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath

from app.config import get_settings
from app.ingestion.filtering import classify_file, is_binary, is_ignored_path, is_secret_file
from app.models.repository_file import RepositoryFileStatus
from app.sources.base import RepositorySource

MVP_INDEXABLE_FILE_TARGET = 2_000
SNIFF_BYTES = 8_192
LANGUAGES = {
    ".js": "javascript",
    ".jsx": "jsx",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
}


@dataclass(frozen=True, slots=True)
class NormalizedFile:
    path: str
    language: str | None
    github_sha: str | None
    content_hash: str | None
    status: RepositoryFileStatus
    size_bytes: int
    content: str | None


async def discover_and_normalize(
    source: RepositorySource,
    revision: str,
) -> list[NormalizedFile]:
    normalized_files: list[NormalizedFile] = []
    for file_ref in await source.list_files(revision):
        if is_ignored_path(file_ref.path) or is_secret_file(file_ref.path):
            continue
        size_limit = get_settings().max_file_size_mb * 1024 * 1024
        content: bytes | None = None
        if file_ref.size_bytes > size_limit:
            status = RepositoryFileStatus.OVERSIZED
        elif is_binary(b"", file_ref.path):
            status = RepositoryFileStatus.BINARY
        else:
            prefix = await source.get_file_prefix(revision, file_ref.path, SNIFF_BYTES)
            if is_binary(prefix, file_ref.path):
                status = RepositoryFileStatus.BINARY
            else:
                content = await source.get_file_content(revision, file_ref.path)
                status = classify_file(file_ref.path, content)
        suffix = PurePosixPath(file_ref.path).suffix.lower()
        normalized_files.append(
            NormalizedFile(
                path=file_ref.path.replace("\\", "/"),
                language=LANGUAGES.get(suffix),
                github_sha=file_ref.github_sha,
                content_hash=(
                    hashlib.sha256(content).hexdigest()
                    if content is not None and status is RepositoryFileStatus.OK
                    else None
                ),
                status=status,
                size_bytes=len(content) if content is not None else file_ref.size_bytes,
                content=(
                    content.decode("utf-8", errors="replace")
                    if content is not None
                    and status is RepositoryFileStatus.OK
                    and suffix in LANGUAGES
                    else None
                ),
            )
        )
    return normalized_files


def exceeds_mvp_file_target(files: list[NormalizedFile]) -> bool:
    return sum(item.status is RepositoryFileStatus.OK for item in files) > MVP_INDEXABLE_FILE_TARGET
