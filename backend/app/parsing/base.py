from typing import Any, Protocol

from pydantic import BaseModel, Field


class ExtractedSymbol(BaseModel):
    name: str
    symbol_type: str
    start_line: int
    end_line: int
    parent_symbol: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportRef(BaseModel):
    module: str
    names: list[str] = Field(default_factory=list)
    alias: str | None = None
    start_line: int
    end_line: int


class ParsedFile(BaseModel):
    file_path: str
    language: str
    symbols: list[ExtractedSymbol]
    imports: list[ImportRef]
    exports: list[str]
    parse_ok: bool
    fallback_used: bool
    metadata: dict[str, Any] = Field(default_factory=dict)


class TreeSitterParser(Protocol):
    language: str

    def parse(self, source: str, file_path: str) -> ParsedFile: ...
