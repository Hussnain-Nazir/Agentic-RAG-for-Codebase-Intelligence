import tree_sitter_typescript
from tree_sitter import Language, Parser

from app.parsing.base import ParsedFile
from app.parsing.javascript_parser import _parse_ecmascript


class TypeScriptTreeSitterParser:
    def __init__(self, tsx: bool = False) -> None:
        self.language = "tsx" if tsx else "typescript"
        grammar = (
            tree_sitter_typescript.language_tsx()
            if tsx
            else tree_sitter_typescript.language_typescript()
        )
        self._parser = Parser(Language(grammar))

    def parse(self, source: str, file_path: str) -> ParsedFile:
        return _parse_ecmascript(self._parser, source, file_path, self.language)
