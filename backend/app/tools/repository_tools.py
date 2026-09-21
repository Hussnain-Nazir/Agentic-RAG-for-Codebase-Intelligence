import uuid
from collections import Counter
from functools import lru_cache
from pathlib import PurePosixPath

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.embeddings.base import EmbeddingProvider
from app.embeddings.local_provider import LocalEmbeddingProvider
from app.evidence.builder import build_evidence
from app.memory.service import MemoryService
from app.models.code_chunk import CodeChunk
from app.models.code_relationship import CodeRelationship, CodeRelationshipKind
from app.models.code_symbol import CodeSymbol
from app.models.finding import Finding, FindingType
from app.models.repository_file import RepositoryFile, RepositoryFileStatus
from app.models.repository_memory import RepositoryMemorySource
from app.models.session import Session
from app.retrieval.expansion import expand_structurally
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.models import RankedChunk
from app.retrieval.symbol_search import symbol_search
from app.tools.base import ExecutionContext
from app.tools.errors import ToolValidationError, UnauthorizedRepositoryAccessError
from app.tools.repository_context import authorize_repository, current_repository_index
from app.tools.schemas import (
    ArchitectureSummary,
    CodeReference,
    CodeReferenceList,
    CodeSymbolList,
    CodeSymbolResult,
    EvidenceList,
    FindReferencesInput,
    FindSymbolInput,
    FindingResult,
    FindingResultList,
    InspectRepositoryInput,
    MemoryResult,
    MemoryResultList,
    RelatedFilesInput,
    RepositoryQueryInput,
    RetrieveMemoryInput,
    ReviewHistoryInput,
    SaveMemoryInput,
)


@lru_cache(maxsize=4)
def _cached_local_embedding_provider(model_name: str) -> LocalEmbeddingProvider:
    return LocalEmbeddingProvider(model_name=model_name)


class SearchCodebaseTool:
    name = "search_codebase"
    description = "Run deterministic hybrid retrieval over a repository index."
    input_schema = RepositoryQueryInput
    output_schema = EvidenceList
    requires_auth = True

    def __init__(
        self,
        session: AsyncSession,
        embedding_provider: EmbeddingProvider | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._embedding_provider = embedding_provider
        self._settings = settings

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        request = RepositoryQueryInput.model_validate(input)
        await authorize_repository(self._session, request.repository_id, ctx)
        index = await current_repository_index(self._session, request.repository_id)
        if self._embedding_provider is None:
            configured = self._settings or get_settings()
            self._embedding_provider = _cached_local_embedding_provider(
                configured.embedding_model_name
            )
        provider = self._embedding_provider
        ranked = await HybridRetriever(
            session=self._session,
            embedding_provider=provider,
        ).retrieve(request.repository_id, index.id, request.query)
        return EvidenceList(build_evidence(ranked[: request.top_k]))


class FindSymbolTool:
    name = "find_symbol"
    description = "Find exact and fuzzy symbols in the current repository index."
    input_schema = FindSymbolInput
    output_schema = CodeSymbolList
    requires_auth = True

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        request = FindSymbolInput.model_validate(input)
        await authorize_repository(self._session, request.repository_id, ctx)
        index = await current_repository_index(self._session, request.repository_id)
        ranked = await symbol_search(
            request.repository_id,
            index.id,
            request.symbol_name,
            session=self._session,
        )
        symbols = list(
            await self._session.scalars(
                select(CodeSymbol).where(CodeSymbol.repository_index_id == index.id)
            )
        )
        by_key = {
            (symbol.file_id, symbol.name, symbol.start_line, symbol.end_line): symbol
            for symbol in symbols
        }
        results: list[CodeSymbolResult] = []
        seen: set[uuid.UUID] = set()
        for candidate in ranked:
            for match in candidate.contained_symbols:
                if match.match_type == "contained":
                    continue
                symbol = by_key.get(
                    (
                        candidate.chunk.file_id,
                        match.name,
                        match.start_line,
                        match.end_line,
                    )
                )
                if symbol is None or symbol.id in seen:
                    continue
                seen.add(symbol.id)
                results.append(
                    CodeSymbolResult(
                        id=symbol.id,
                        repository_index_id=symbol.repository_index_id,
                        file_id=symbol.file_id,
                        file_path=candidate.chunk.file_path,
                        name=symbol.name,
                        symbol_type=symbol.symbol_type,
                        start_line=symbol.start_line,
                        end_line=symbol.end_line,
                        parent_symbol=symbol.parent_symbol,
                        match_type=match.match_type,
                        score=candidate.raw_score,
                    )
                )
        return CodeSymbolList(results)


class FindReferencesTool:
    name = "find_references"
    description = "Find stored structural references to a named symbol."
    input_schema = FindReferencesInput
    output_schema = CodeReferenceList
    requires_auth = True

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        request = FindReferencesInput.model_validate(input)
        await authorize_repository(self._session, request.repository_id, ctx)
        index = await current_repository_index(self._session, request.repository_id)
        targets = list(
            await self._session.scalars(
                select(CodeSymbol).where(
                    CodeSymbol.repository_index_id == index.id,
                    CodeSymbol.name == request.symbol_name,
                )
            )
        )
        if not targets:
            targets = list(
                await self._session.scalars(
                    select(CodeSymbol).where(
                        CodeSymbol.repository_index_id == index.id,
                        func.lower(CodeSymbol.name) == request.symbol_name.lower(),
                    )
                )
            )
        if not targets:
            return CodeReferenceList([])
        relationships = list(
            await self._session.scalars(
                select(CodeRelationship)
                .where(
                    CodeRelationship.repository_index_id == index.id,
                    CodeRelationship.to_symbol_id.in_([item.id for item in targets]),
                )
                .order_by(
                    CodeRelationship.kind,
                    CodeRelationship.from_symbol_id,
                    CodeRelationship.id,
                )
            )
        )
        if not relationships:
            return CodeReferenceList([])
        source_ids = {item.from_symbol_id for item in relationships}
        sources = {
            item.id: item
            for item in await self._session.scalars(
                select(CodeSymbol).where(
                    CodeSymbol.repository_index_id == index.id,
                    CodeSymbol.id.in_(source_ids),
                )
            )
        }
        files = {
            item.id: item
            for item in await self._session.scalars(
                select(RepositoryFile).where(
                    RepositoryFile.repository_index_id == index.id,
                    RepositoryFile.id.in_({item.file_id for item in sources.values()}),
                )
            )
        }
        references: list[CodeReference] = []
        for relationship in relationships:
            source = sources.get(relationship.from_symbol_id)
            if source is None:
                continue
            file = files.get(source.file_id)
            if file is None:
                continue
            references.append(
                CodeReference(
                    file=file.path,
                    symbol=source.name,
                    line=source.start_line,
                    relationship_kind=relationship.kind.value,
                    confidence=relationship.confidence.value,
                )
            )
        return CodeReferenceList(references)


class GetRelatedFilesTool:
    name = "get_related_files"
    description = "Expand a symbol or chunk to directly related stored evidence."
    input_schema = RelatedFilesInput
    output_schema = EvidenceList
    requires_auth = True

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        request = RelatedFilesInput.model_validate(input)
        await authorize_repository(self._session, request.repository_id, ctx)
        index = await current_repository_index(self._session, request.repository_id)
        seeds: list[RankedChunk] = []
        try:
            chunk_id = uuid.UUID(request.symbol_name_or_chunk_id)
        except ValueError:
            chunk_id = None
        if chunk_id is not None:
            chunk = await self._session.scalar(
                select(CodeChunk).where(
                    CodeChunk.id == chunk_id,
                    CodeChunk.repository_id == request.repository_id,
                    CodeChunk.repository_index_id == index.id,
                )
            )
            if chunk is not None:
                seeds = [RankedChunk(chunk=chunk, raw_score=1.0, signal="symbol")]
        else:
            seeds = await symbol_search(
                request.repository_id,
                index.id,
                request.symbol_name_or_chunk_id,
                session=self._session,
            )
        if not seeds:
            return EvidenceList([])
        seed_ids = {item.chunk.id for item in seeds}
        expanded = await expand_structurally(seeds, session=self._session)
        related = [
            item for item in expanded
            if request.include_seed or item.chunk.id not in seed_ids
        ]
        evidence = build_evidence(related)
        if chunk_id is None:
            source_symbols = list(
                await self._session.scalars(
                    select(CodeSymbol).where(
                        CodeSymbol.repository_index_id == index.id,
                        func.lower(CodeSymbol.name)
                        == request.symbol_name_or_chunk_id.lower(),
                    )
                )
            )
            if source_symbols:
                relationships = list(
                    await self._session.scalars(
                        select(CodeRelationship).where(
                            CodeRelationship.repository_index_id == index.id,
                            CodeRelationship.from_symbol_id.in_(
                                [item.id for item in source_symbols]
                            ),
                            CodeRelationship.kind.in_(
                                [
                                    CodeRelationshipKind.CALLS,
                                    CodeRelationshipKind.API_CALL,
                                ]
                            ),
                        )
                    )
                )
                symbols_by_id = {
                    item.id: item
                    for item in list(
                        await self._session.scalars(
                            select(CodeSymbol).where(
                                CodeSymbol.repository_index_id == index.id
                            )
                        )
                    )
                }
                files_by_id = {
                    item.id: item.path
                    for item in list(
                        await self._session.scalars(
                            select(RepositoryFile).where(
                                RepositoryFile.repository_index_id == index.id
                            )
                        )
                    )
                }
                edges: list[dict[str, object]] = []
                seen_edges: set[tuple[uuid.UUID, uuid.UUID, str]] = set()
                for relationship in relationships:
                    target = (
                        symbols_by_id.get(relationship.to_symbol_id)
                        if relationship.to_symbol_id
                        else None
                    )
                    source = symbols_by_id.get(relationship.from_symbol_id)
                    if source is None or target is None:
                        continue
                    key = (source.id, target.id, relationship.kind.value)
                    if key in seen_edges:
                        continue
                    seen_edges.add(key)
                    edges.append(
                        {
                            "source_symbol": source.name,
                            "source_file": files_by_id.get(source.file_id),
                            "target_symbol": target.name,
                            "target_file": files_by_id.get(target.file_id),
                            "target_start_line": target.start_line,
                            "target_end_line": target.end_line,
                            "kind": relationship.kind.value,
                            "confidence": relationship.confidence.value,
                            "observed_by": self.name,
                        }
                    )
                for item in evidence:
                    item.relationship_metadata["flow_edges"] = edges
        return EvidenceList(evidence)


class InspectRepositoryTool:
    name = "inspect_repository"
    description = "Build deterministic architecture metadata from stored files."
    input_schema = InspectRepositoryInput
    output_schema = ArchitectureSummary
    requires_auth = True

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        request = InspectRepositoryInput.model_validate(input)
        await authorize_repository(self._session, request.repository_id, ctx)
        index = await current_repository_index(self._session, request.repository_id)
        files = list(
            (await self._session.execute(
                select(RepositoryFile.path, RepositoryFile.language, RepositoryFile.status)
                .where(RepositoryFile.repository_index_id == index.id)
                .order_by(RepositoryFile.path)
            )).all()
        )
        languages = Counter(
            language
            for _, language, file_status in files
            if language and file_status is RepositoryFileStatus.OK
        )
        folders = sorted(
            {
                PurePosixPath(path).parts[0]
                for path, _, _ in files
                if len(PurePosixPath(path).parts) > 1
            }
        )
        manifest_names = {"package.json", "requirements.txt", "pyproject.toml"}
        manifest_paths = [
            path for path, _, _ in files
            if PurePosixPath(path).name in manifest_names
        ]
        manifest_contents = (
            list(await self._session.scalars(
                select(RepositoryFile.content).where(
                    RepositoryFile.repository_index_id == index.id,
                    RepositoryFile.path.in_(manifest_paths),
                )
            ))
            if manifest_paths else []
        )
        manifest_text = "\n".join(
            content or "" for content in manifest_contents
        ).lower()
        frameworks: list[str] = []
        if "fastapi" in manifest_text:
            frameworks.append("FastAPI")
        if '"react"' in manifest_text or "react==" in manifest_text:
            frameworks.append("React")
        if '"vite"' in manifest_text or "vite==" in manifest_text:
            frameworks.append("Vite")
        entry_names = {
            "app.py",
            "main.py",
            "src/main.js",
            "src/main.jsx",
            "src/main.ts",
            "src/main.tsx",
        }
        entrypoints = sorted(
            path
            for path, _, _ in files
            if path in entry_names
            or PurePosixPath(path).name in {"app.py", "main.py"}
        )
        tests = sorted(
            path
            for path, _, _ in files
            if PurePosixPath(path).name.startswith("test_")
            or ".test." in PurePosixPath(path).name
            or ".spec." in PurePosixPath(path).name
            or "tests" in PurePosixPath(path).parts
        )
        return ArchitectureSummary(
            repository_id=request.repository_id,
            repository_index_id=index.id,
            repository_index_version=index.version,
            languages=dict(sorted(languages.items())),
            top_level_folders=folders,
            frameworks_detected=frameworks,
            likely_entrypoints=entrypoints,
            test_locations=tests,
        )


class RetrieveMemoryTool:
    name = "retrieve_memory"
    description = "Retrieve relevant repository or session memory."
    input_schema = RetrieveMemoryInput
    output_schema = MemoryResultList
    requires_auth = True

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._service = MemoryService(session)

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        request = RetrieveMemoryInput.model_validate(input)
        await authorize_repository(self._session, request.repository_id, ctx)
        if request.scope == "session":
            if ctx.session_id is None:
                raise ToolValidationError("Session scope requires session_id")
            conversation = await self._session.get(Session, ctx.session_id)
            if (
                conversation is None
                or conversation.repository_id != request.repository_id
                or conversation.user_id != ctx.user_id
            ):
                raise UnauthorizedRepositoryAccessError("Session access denied")
            summary = await self._service.retrieve_session_memory(
                ctx.session_id, request.query
            )
            return MemoryResultList(
                []
                if not summary
                else [
                    MemoryResult(
                        repository_id=request.repository_id,
                        scope="session",
                        topic=request.query,
                        content=summary,
                    )
                ]
            )
        rows = await self._service.retrieve_repository_memory(
            request.repository_id, request.query
        )
        return MemoryResultList(
            [
                MemoryResult(
                    id=row.id,
                    repository_id=row.repository_id,
                    repository_index_version=row.repository_index_version,
                    type=row.type.value,
                    scope=row.scope,
                    topic=row.topic,
                    content=row.content,
                    evidence_ids=[uuid.UUID(item) for item in row.evidence_ids],
                    confidence=row.confidence.value,
                    is_stale=row.is_stale,
                    source=row.source.value,
                )
                for row in rows
            ]
        )


class SaveMemoryTool:
    name = "save_memory"
    description = "Persist an explicit evidence-grounded repository fact."
    input_schema = SaveMemoryInput
    output_schema = MemoryResult
    requires_auth = True

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._service = MemoryService(session)

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        request = SaveMemoryInput.model_validate(input)
        await authorize_repository(self._session, request.repository_id, ctx)
        await current_repository_index(self._session, request.repository_id)
        row = await self._service.save_repository_memory(
            request.repository_id,
            request.type,
            request.content,
            request.evidence_ids,
            RepositoryMemorySource.EXPLICIT,
        )
        return MemoryResult(
            id=row.id,
            repository_id=row.repository_id,
            repository_index_version=row.repository_index_version,
            type=row.type.value,
            scope=row.scope,
            topic=row.topic,
            content=row.content,
            evidence_ids=[uuid.UUID(item) for item in row.evidence_ids],
            confidence=row.confidence.value,
            is_stale=row.is_stale,
            source=row.source.value,
        )


class GetReviewHistoryTool:
    name = "get_review_history"
    description = "Retrieve previously saved optional review findings."
    input_schema = ReviewHistoryInput
    output_schema = FindingResultList
    requires_auth = True

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, input: BaseModel, ctx: ExecutionContext) -> BaseModel:
        request = ReviewHistoryInput.model_validate(input)
        await authorize_repository(self._session, request.repository_id, ctx)
        statement = select(Finding).where(
            Finding.repository_id == request.repository_id,
            Finding.type == FindingType.REVIEW,
        )
        if request.category is not None:
            statement = statement.where(
                Finding.content["category"].as_string() == request.category
            )
        rows = list(
            await self._session.scalars(
                statement.order_by(Finding.created_at.desc(), Finding.id)
            )
        )
        return FindingResultList(
            [
                FindingResult(
                    id=row.id,
                    repository_id=row.repository_id,
                    session_id=row.session_id,
                    type=row.type.value,
                    title=row.title,
                    content=row.content,
                    evidence_ids=[uuid.UUID(item) for item in row.evidence_ids],
                    created_at=row.created_at,
                )
                for row in rows
            ]
        )
