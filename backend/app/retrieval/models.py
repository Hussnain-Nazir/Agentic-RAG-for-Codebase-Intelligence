from dataclasses import dataclass, field
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
    final_score: float | None = None
    raw_signal_scores: dict[str, float] = field(default_factory=dict)
    contributing_signals: tuple[RetrievalSignal, ...] = ()

    def __post_init__(self) -> None:
        if self.final_score is None:
            object.__setattr__(self, "final_score", self.raw_score)
        if not self.raw_signal_scores and self.signal in {
            "semantic",
            "lexical",
            "symbol",
        }:
            object.__setattr__(
                self,
                "raw_signal_scores",
                {self.signal: self.raw_score},
            )
        if not self.contributing_signals:
            object.__setattr__(self, "contributing_signals", (self.signal,))
