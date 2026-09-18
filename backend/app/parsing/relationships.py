from dataclasses import dataclass

from app.models.code_relationship import (
    CodeRelationshipConfidence,
    CodeRelationshipKind,
)
from app.parsing.base import ParsedFile


@dataclass(frozen=True, slots=True)
class ExtractedRelationship:
    from_symbol: str
    to_symbol: str | None
    kind: CodeRelationshipKind
    confidence: CodeRelationshipConfidence


def extract_relationships(parsed: ParsedFile) -> list[ExtractedRelationship]:
    symbols_by_name = {
        name: [symbol for symbol in parsed.symbols if symbol.name == name]
        for name in {symbol.name for symbol in parsed.symbols}
    }
    relationships: set[ExtractedRelationship] = set()

    for symbol in parsed.symbols:
        calls = set(symbol.metadata.get("calls", []))
        for target in calls:
            candidates = symbols_by_name.get(target, [])
            directly_resolved = len(candidates) == 1 and (
                candidates[0].parent_symbol is None
                or candidates[0].parent_symbol == symbol.parent_symbol
            )
            relationships.add(
                ExtractedRelationship(
                    from_symbol=symbol.name,
                    to_symbol=target,
                    kind=CodeRelationshipKind.CALLS,
                    confidence=(
                        CodeRelationshipConfidence.HIGH
                        if directly_resolved
                        else CodeRelationshipConfidence.LOW
                    ),
                )
            )
        for target in set(symbol.metadata.get("references", [])) - calls - {symbol.name}:
            if target in symbols_by_name:
                relationships.add(
                    ExtractedRelationship(
                        from_symbol=symbol.name,
                        to_symbol=target,
                        kind=CodeRelationshipKind.REFERENCES,
                        confidence=CodeRelationshipConfidence.LOW,
                    )
                )
        for target in symbol.metadata.get("bases", []):
            candidates = symbols_by_name.get(target, [])
            directly_resolved = len(candidates) == 1 and candidates[0].symbol_type in {
                "CLASS",
                "INTERFACE",
            }
            relationships.add(
                ExtractedRelationship(
                    from_symbol=symbol.name,
                    to_symbol=target,
                    kind=CodeRelationshipKind.EXTENDS,
                    confidence=(
                        CodeRelationshipConfidence.HIGH
                        if directly_resolved
                        else CodeRelationshipConfidence.LOW
                    ),
                )
            )
        for route in symbol.metadata.get("api_calls", []):
            relationships.add(
                ExtractedRelationship(
                    from_symbol=symbol.name,
                    to_symbol=None,
                    kind=CodeRelationshipKind.API_CALL,
                    confidence=CodeRelationshipConfidence.LOW,
                )
            )

    source_symbol = next((item.name for item in parsed.symbols if item.parent_symbol is None), None)
    if source_symbol:
        for imported in parsed.imports:
            for target in imported.names:
                relationships.add(
                    ExtractedRelationship(
                        from_symbol=source_symbol,
                        to_symbol=target,
                        kind=CodeRelationshipKind.IMPORTS,
                        confidence=CodeRelationshipConfidence.LOW,
                    )
                )
    return sorted(
        relationships,
        key=lambda item: (item.from_symbol, item.kind.value, item.to_symbol or ""),
    )
