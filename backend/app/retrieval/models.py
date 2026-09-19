from dataclasses import dataclass
from typing import Literal

from app.models.code_chunk import CodeChunk

RetrievalSignal = Literal["semantic", "lexical", "symbol"]


@dataclass(frozen=True, slots=True)
class RankedChunk:
    chunk: CodeChunk
    raw_score: float
    signal: RetrievalSignal
