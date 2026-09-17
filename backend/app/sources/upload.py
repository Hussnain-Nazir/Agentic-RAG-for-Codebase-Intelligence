import hashlib
from pathlib import Path, PurePosixPath
from typing import Literal

from app.ingestion.filtering import is_ignored_path, is_secret_file
from app.sources.base import SourceFileRef


class UploadedRepositorySource:
    source_type: Literal["upload"] = "upload"

    async def list_files(self, ref: str) -> list[SourceFileRef]:
        root = Path(ref).resolve()
        gitignore = root / ".gitignore"
        patterns = (
            gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
            if gitignore.is_file()
            else []
        )
        files: list[SourceFileRef] = []
        for file_path in root.rglob("*"):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(root).as_posix()
            if is_ignored_path(relative, patterns) or is_secret_file(relative):
                continue
            files.append(SourceFileRef(path=relative, size_bytes=file_path.stat().st_size))
        return sorted(files, key=lambda item: item.path)

    async def get_file_content(self, ref: str, path: str) -> bytes:
        root = Path(ref).resolve()
        normalized = PurePosixPath(path.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"Invalid repository path: {path}")
        target = (root / Path(*normalized.parts)).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"Repository path escapes the source root: {path}")
        return target.read_bytes()

    async def get_revision(self, ref: str) -> str:
        tree_hash = hashlib.sha256()
        for file_ref in await self.list_files(ref):
            content = await self.get_file_content(ref, file_ref.path)
            content_hash = hashlib.sha256(content).hexdigest()
            tree_hash.update(file_ref.path.encode("utf-8"))
            tree_hash.update(b"\x00")
            tree_hash.update(content_hash.encode("ascii"))
            tree_hash.update(b"\n")
        return tree_hash.hexdigest()
