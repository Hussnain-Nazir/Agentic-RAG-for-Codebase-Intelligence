import uuid
from typing import Any, Literal

from pydantic import BaseModel


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
