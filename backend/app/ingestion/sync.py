import asyncio
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.embeddings.base import EmbeddingProvider
from app.github.client import GitHubClient
from app.ingestion.embedding_stage import (
    current_embedding_model_version,
    embed_repository_chunks,
)
from app.ingestion.filtering import is_ignored_path, is_secret_file
from app.ingestion.pipeline import MVP_INDEXABLE_FILE_TARGET, discover_and_normalize
from app.ingestion.parsing_stage import parse_repository_files
from app.ingestion.chunking_stage import chunk_repository_files
from app.memory.service import MemoryService
from app.models.code_chunk import CodeChunk
from app.models.code_relationship import CodeRelationship
from app.models.code_symbol import CodeSymbol
from app.models.github_installation import GitHubInstallation, GitHubInstallationStatus
from app.models.repository import (
    Repository,
    RepositoryAccessStatus,
    RepositorySourceType,
)
from app.models.repository_file import RepositoryFile, RepositoryFileStatus
from app.models.repository_index import RepositoryIndex, RepositoryIndexState
from app.models.repository_memory import RepositoryMemory
from app.parsing.base import ParsedFile
from app.parsing.relationships import extract_relationships
from app.sources.base import SourceFileRef
from app.sources.github import GitHubRepositorySource


class SyncInProgressError(RuntimeError):
    pass


class SyncUnavailableError(RuntimeError):
    pass


_ACTIVE_STATES = (
    RepositoryIndexState.PENDING,
    RepositoryIndexState.DISCOVERING,
    RepositoryIndexState.PARSING,
    RepositoryIndexState.EMBEDDING,
    RepositoryIndexState.INDEXING,
)
_locks: dict[uuid.UUID, asyncio.Lock] = {}


@dataclass(slots=True)
class _SelectedSource:
    source: GitHubRepositorySource
    refs: list[SourceFileRef]
    source_type: str = "github"

    async def list_files(self, ref: str) -> list[SourceFileRef]:
        return self.refs

    async def get_file_content(self, ref: str, path: str) -> bytes:
        return await self.source.get_file_content(ref, path)

    async def get_revision(self, ref: str) -> str:
        return await self.source.get_revision(ref)


def _copy_file(old: RepositoryFile, index_id: uuid.UUID) -> RepositoryFile:
    return RepositoryFile(
        repository_index_id=index_id,
        path=old.path,
        language=old.language,
        github_sha=old.github_sha,
        content_hash=old.content_hash,
        status=old.status,
        size_bytes=old.size_bytes,
        content=old.content,
    )


def _copy_chunk(
    old: CodeChunk,
    index_id: uuid.UUID,
    file_id: uuid.UUID,
    *,
    embedding_version: str,
) -> CodeChunk:
    reusable = old.embedding_model_version == embedding_version
    return CodeChunk(
        repository_id=old.repository_id,
        repository_index_id=index_id,
        file_id=file_id,
        file_path=old.file_path,
        language=old.language,
        chunk_type=old.chunk_type,
        symbol_name=old.symbol_name,
        symbol_type=old.symbol_type,
        parent_symbol=old.parent_symbol,
        start_line=old.start_line,
        end_line=old.end_line,
        content=old.content,
        content_hash=old.content_hash,
        embedding=old.embedding if reusable else None,
        embedding_model_version=old.embedding_model_version if reusable else None,
        chunk_metadata=dict(old.chunk_metadata),
    )


async def _relink_changed_sources(
    session: AsyncSession,
    index_id: uuid.UUID,
    parsed_files: list[ParsedFile],
    files_by_path: dict[str, RepositoryFile],
) -> None:
    symbols = list(
        await session.scalars(
            select(CodeSymbol).where(CodeSymbol.repository_index_id == index_id)
        )
    )
    by_file_name = {(item.file_id, item.name): item for item in symbols}
    by_name: dict[str, list[CodeSymbol]] = {}
    for symbol in symbols:
        by_name.setdefault(symbol.name, []).append(symbol)
    changed_file_ids = {files_by_path[item.file_path].id for item in parsed_files}
    changed_ids = {
        symbol.id for symbol in symbols if symbol.file_id in changed_file_ids
    }
    if changed_ids:
        await session.execute(
            delete(CodeRelationship).where(
                CodeRelationship.repository_index_id == index_id,
                CodeRelationship.from_symbol_id.in_(changed_ids),
            )
        )
    for parsed in parsed_files:
        file = files_by_path[parsed.file_path]
        for extracted in extract_relationships(parsed):
            source = by_file_name.get((file.id, extracted.from_symbol))
            if source is None:
                continue
            target = by_file_name.get((file.id, extracted.to_symbol))
            if target is None and extracted.to_symbol:
                candidates = by_name.get(extracted.to_symbol, [])
                target = candidates[0] if len(candidates) == 1 else None
            session.add(
                CodeRelationship(
                    repository_index_id=index_id,
                    from_symbol_id=source.id,
                    to_symbol_id=target.id if target else None,
                    kind=extracted.kind,
                    confidence=extracted.confidence,
                )
            )
    await session.flush()


async def synchronize_repository(
    repository_id: uuid.UUID,
    *,
    session: AsyncSession,
    github_client: GitHubClient,
    embedding_provider: EmbeddingProvider,
    settings: Settings,
) -> RepositoryIndex:
    lock = _locks.setdefault(repository_id, asyncio.Lock())
    if lock.locked():
        raise SyncInProgressError("Repository synchronization is already in progress")
    async with lock:
        repository = await session.scalar(
            select(Repository)
            .where(Repository.id == repository_id)
            .with_for_update()
        )
        if repository is None or repository.source_type is not RepositorySourceType.GITHUB:
            raise SyncUnavailableError("Only imported GitHub repositories can be synchronized")
        if repository.access_status is not RepositoryAccessStatus.ACTIVE:
            raise SyncUnavailableError("Repository source access is unavailable")
        if repository.github_installation_id is None or repository.github_repo_id is None:
            raise SyncUnavailableError("GitHub installation is unavailable")
        installation = await session.get(GitHubInstallation, repository.github_installation_id)
        if installation is None or installation.status is not GitHubInstallationStatus.ACTIVE:
            raise SyncUnavailableError("GitHub installation is unavailable")
        active = await session.scalar(
            select(RepositoryIndex.id).where(
                RepositoryIndex.repository_id == repository_id,
                RepositoryIndex.state.in_(_ACTIVE_STATES),
            )
        )
        if active is not None:
            raise SyncInProgressError("Repository synchronization is already in progress")
        old_index = await session.scalar(
            select(RepositoryIndex)
            .where(
                RepositoryIndex.repository_id == repository_id,
                RepositoryIndex.state.in_(
                    (RepositoryIndexState.READY, RepositoryIndexState.PARTIAL)
                ),
            )
            .order_by(RepositoryIndex.version.desc())
            .limit(1)
        )
        if old_index is None:
            raise SyncUnavailableError("Repository has no ready index")
        max_version = await session.scalar(
            select(func.max(RepositoryIndex.version)).where(
                RepositoryIndex.repository_id == repository_id
            )
        )
        source = GitHubRepositorySource(
            github_client, installation.installation_id, repository.github_repo_id
        )
        revision = await source.get_revision(repository.selected_branch)
        index = RepositoryIndex(
            repository_id=repository_id,
            version=int(max_version or 0) + 1,
            revision=revision,
            state=RepositoryIndexState.PENDING,
        )
        session.add(index)
        await session.commit()
        try:
            index.state = RepositoryIndexState.DISCOVERING
            refs = [
                item
                for item in await source.list_files_at_revision(
                    repository.selected_branch, revision
                )
                if not is_ignored_path(item.path) and not is_secret_file(item.path)
            ]
            refs_by_path = {item.path.replace("\\", "/"): item for item in refs}
            old_files = list(
                await session.scalars(
                    select(RepositoryFile).where(
                        RepositoryFile.repository_index_id == old_index.id
                    )
                )
            )
            old_by_path = {item.path: item for item in old_files}
            unchanged_paths = {
                path
                for path, item in refs_by_path.items()
                if path in old_by_path and old_by_path[path].github_sha == item.github_sha
            }
            changed_paths = set(refs_by_path) - unchanged_paths
            deleted_paths = set(old_by_path) - set(refs_by_path)
            selected_refs = [refs_by_path[path] for path in sorted(changed_paths)]
            normalized = await discover_and_normalize(
                _SelectedSource(source, selected_refs), repository.selected_branch
            )
            file_map: dict[uuid.UUID, RepositoryFile] = {}
            new_files: list[RepositoryFile] = []
            for path in sorted(unchanged_paths):
                old_file = old_by_path[path]
                copied = _copy_file(old_file, index.id)
                session.add(copied)
                new_files.append(copied)
                file_map[old_file.id] = copied
            changed_files: list[RepositoryFile] = []
            for item in normalized:
                file = RepositoryFile(
                    repository_index_id=index.id,
                    path=item.path,
                    language=item.language,
                    github_sha=item.github_sha,
                    content_hash=item.content_hash,
                    status=item.status,
                    size_bytes=item.size_bytes,
                    content=item.content,
                )
                session.add(file)
                new_files.append(file)
                changed_files.append(file)
            await session.flush()
            index.files_discovered = len(new_files)
            index.files_processed = sum(
                item.status is RepositoryFileStatus.OK for item in new_files
            )
            index.size_warning = index.files_processed > MVP_INDEXABLE_FILE_TARGET
            index.state = RepositoryIndexState.PARSING
            parsed = await parse_repository_files(changed_files) if changed_files else []
            index.files_failed = sum(
                item.status is RepositoryFileStatus.PARSE_FAILED for item in new_files
            )
            if changed_files:
                await chunk_repository_files(changed_files, parsed)
            index.state = RepositoryIndexState.EMBEDDING
            await session.flush()
            changed_chunks = list(
                await session.scalars(
                    select(CodeChunk).where(CodeChunk.repository_index_id == index.id)
                )
            )
            await embed_repository_chunks(
                changed_chunks, embedding_provider, settings=settings
            )
            old_chunks = list(
                await session.scalars(
                    select(CodeChunk).where(CodeChunk.repository_index_id == old_index.id)
                )
            )
            current_version = current_embedding_model_version(settings)
            chunk_map: dict[uuid.UUID, CodeChunk] = {}
            copied_chunks: list[CodeChunk] = []
            for old in old_chunks:
                file = file_map.get(old.file_id)
                if file is None:
                    continue
                copied = _copy_chunk(
                    old, index.id, file.id, embedding_version=current_version
                )
                session.add(copied)
                copied_chunks.append(copied)
                chunk_map[old.id] = copied
            old_symbols = list(
                await session.scalars(
                    select(CodeSymbol).where(CodeSymbol.repository_index_id == old_index.id)
                )
            )
            symbol_map: dict[uuid.UUID, CodeSymbol] = {}
            for old in old_symbols:
                file = file_map.get(old.file_id)
                if file is None:
                    continue
                copied = CodeSymbol(
                    repository_index_id=index.id,
                    file_id=file.id,
                    name=old.name,
                    symbol_type=old.symbol_type,
                    start_line=old.start_line,
                    end_line=old.end_line,
                    parent_symbol=old.parent_symbol,
                )
                session.add(copied)
                symbol_map[old.id] = copied
            await session.flush()
            new_symbols = list(
                await session.scalars(
                    select(CodeSymbol).where(CodeSymbol.repository_index_id == index.id)
                )
            )
            new_file_by_id = {item.id: item.path for item in new_files}
            new_symbol_by_key: dict[tuple[str, str, str | None], CodeSymbol] = {
                (new_file_by_id[item.file_id], item.name, item.parent_symbol): item
                for item in new_symbols
            }
            old_file_by_id = {item.id: item.path for item in old_files}
            for old in old_symbols:
                if old.id in symbol_map:
                    continue
                path = old_file_by_id[old.file_id]
                symbol = new_symbol_by_key.get((path, old.name, old.parent_symbol))
                if symbol is not None:
                    symbol_map[old.id] = symbol
            old_relationships = list(
                await session.scalars(
                    select(CodeRelationship).where(
                        CodeRelationship.repository_index_id == old_index.id
                    )
                )
            )
            unchanged_symbol_ids = {
                symbol.id for symbol in old_symbols if symbol.file_id in file_map
            }
            for old in old_relationships:
                source_symbol = symbol_map.get(old.from_symbol_id)
                if source_symbol is None or old.from_symbol_id not in unchanged_symbol_ids:
                    continue
                target_symbol = (
                    symbol_map.get(old.to_symbol_id) if old.to_symbol_id else None
                )
                if old.to_symbol_id is not None and target_symbol is None:
                    continue
                session.add(
                    CodeRelationship(
                        repository_index_id=index.id,
                        from_symbol_id=source_symbol.id,
                        to_symbol_id=target_symbol.id if target_symbol else None,
                        kind=old.kind,
                        confidence=old.confidence,
                    )
                )
            await _relink_changed_sources(
                session,
                index.id,
                parsed,
                {item.path: item for item in changed_files},
            )
            if any(item.embedding is None for item in copied_chunks):
                await embed_repository_chunks(
                    copied_chunks, embedding_provider, settings=settings
                )
            await MemoryService(session).invalidate_stale(
                repository_id, sorted(changed_paths | deleted_paths)
            )
            memories = list(
                await session.scalars(
                    select(RepositoryMemory).where(
                        RepositoryMemory.repository_id == repository_id,
                        RepositoryMemory.repository_index_version == old_index.version,
                        RepositoryMemory.is_stale.is_(False),
                    )
                )
            )
            for memory in memories:
                old_ids = [uuid.UUID(str(value)) for value in memory.evidence_ids]
                if all(item in chunk_map for item in old_ids):
                    memory.evidence_ids = [str(chunk_map[item].id) for item in old_ids]
                    memory.repository_index_version = index.version
                else:
                    memory.is_stale = True
            index.state = RepositoryIndexState.INDEXING
            await session.flush()
            index.state = (
                RepositoryIndexState.PARTIAL
                if index.files_failed else RepositoryIndexState.READY
            )
            await session.commit()
            return index
        except Exception as exc:
            await session.rollback()
            failed = await session.get(RepositoryIndex, index.id)
            if failed is not None:
                failed.state = RepositoryIndexState.FAILED
                failed.failure_reason = f"Synchronization failed: {type(exc).__name__}"
                await session.commit()
            raise
