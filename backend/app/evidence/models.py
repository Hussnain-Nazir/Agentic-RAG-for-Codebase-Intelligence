import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Evidence(BaseModel):
    evidence_id: uuid.UUID
    repository_id: uuid.UUID
    repository_index_id: uuid.UUID
    source_type: Literal["CODE", "DOCUMENTATION", "WEB"]
    file_path: str | None
    symbol: str | None
    start_line: int | None
    end_line: int | None
    content_excerpt: str
    relationship_metadata: dict[str, Any]
    retrieval_metadata: dict[str, Any]
    external_source_metadata: dict[str, Any] | None


class EvidenceQuality(str, Enum):
    STRONG = "STRONG"
    INCOMPLETE = "INCOMPLETE"
    CONFLICTING = "CONFLICTING"
    NONE = "NONE"


class ContextTask(BaseModel):
    query: str
    extracted_keywords: list[str] = Field(default_factory=list)


class RepositoryMemoryContextItem(BaseModel):
    id: uuid.UUID | None = None
    repository_id: uuid.UUID | None = None
    repository_index_version: int | None = None
    scope: str | None = None
    topic: str
    content: str
    tags: list[str] = Field(default_factory=list)
    evidence_ids: list[uuid.UUID] = Field(default_factory=list)
    confidence: str | None = None
    source: str | None = None
    is_stale: bool = False


class WebEvidenceItem(BaseModel):
    title: str
    url: str
    snippet: str
    source_domain: str
    retrieved_at: datetime | None = None
    score: float = 0.0
    repository_id: uuid.UUID | None = None
    repository_index_id: uuid.UUID | None = None


class EvidenceContext(BaseModel):
    context_id: uuid.UUID
    task: ContextTask
    task_type: str
    repository_memory: list[RepositoryMemoryContextItem]
    evidence: list[Evidence]
    quality: EvidenceQuality
    estimated_tokens: int
