import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, RootModel, model_validator

from app.evidence.models import Evidence


class RepositoryQueryInput(BaseModel):
    repository_id: uuid.UUID
    query: str = Field(min_length=1)
    top_k: int = Field(default=12, ge=1)


class EvidenceList(RootModel[list[Evidence]]):
    pass


class FindSymbolInput(BaseModel):
    repository_id: uuid.UUID
    symbol_name: str = Field(min_length=1)


class CodeSymbolResult(BaseModel):
    id: uuid.UUID
    repository_index_id: uuid.UUID
    file_id: uuid.UUID
    file_path: str
    name: str
    symbol_type: str
    start_line: int
    end_line: int
    parent_symbol: str | None
    match_type: str
    score: float


class CodeSymbolList(RootModel[list[CodeSymbolResult]]):
    pass


class FindReferencesInput(BaseModel):
    repository_id: uuid.UUID
    symbol_name: str = Field(min_length=1)


class CodeReference(BaseModel):
    file: str
    symbol: str
    line: int
    relationship_kind: str
    confidence: str


class CodeReferenceList(RootModel[list[CodeReference]]):
    pass


class RelatedFilesInput(BaseModel):
    repository_id: uuid.UUID
    symbol_name_or_chunk_id: str = Field(min_length=1)
    include_seed: bool = False


class InspectRepositoryInput(BaseModel):
    repository_id: uuid.UUID


class ArchitectureSummary(BaseModel):
    repository_id: uuid.UUID
    repository_index_id: uuid.UUID
    repository_index_version: int
    languages: dict[str, int]
    top_level_folders: list[str]
    frameworks_detected: list[str]
    likely_entrypoints: list[str]
    test_locations: list[str]


class RetrieveMemoryInput(BaseModel):
    repository_id: uuid.UUID
    scope: Literal["repository", "session"]
    query: str = ""


class MemoryResult(BaseModel):
    id: uuid.UUID | None = None
    repository_id: uuid.UUID
    repository_index_version: int | None = None
    type: str | None = None
    scope: str
    topic: str
    content: str
    evidence_ids: list[uuid.UUID] = Field(default_factory=list)
    confidence: str | None = None
    is_stale: bool = False
    source: str | None = None


class MemoryResultList(RootModel[list[MemoryResult]]):
    pass


class SaveMemoryInput(BaseModel):
    repository_id: uuid.UUID
    type: Literal["FACT", "ARCHITECTURE", "CONVENTION"]
    content: str = Field(min_length=1)
    evidence_ids: list[uuid.UUID]

    @model_validator(mode="after")
    def require_evidence(self):
        if not self.evidence_ids:
            raise ValueError("At least one evidence_id is required")
        return self


class ReviewHistoryInput(BaseModel):
    repository_id: uuid.UUID
    category: str | None = None


class FindingResult(BaseModel):
    id: uuid.UUID
    repository_id: uuid.UUID
    session_id: uuid.UUID | None
    type: str
    title: str
    content: dict[str, Any]
    evidence_ids: list[uuid.UUID]
    created_at: datetime


class FindingResultList(RootModel[list[FindingResult]]):
    pass
