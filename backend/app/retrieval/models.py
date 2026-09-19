from dataclasses import dataclass
from typing import Literal
import uuid

from app.models.code_chunk import CodeChunk

RetrievalSignal = Literal[
    "semantic",
    "lexical",
    "symbol",
    "hybrid",
    "structural",
]


@dataclass(frozen=True, slots=True)
class RankedChunk:
    chunk: CodeChunk
    raw_score: float
    signal: RetrievalSignal
    source_chunk_ids: tuple[uuid.UUID, ...] = ()
