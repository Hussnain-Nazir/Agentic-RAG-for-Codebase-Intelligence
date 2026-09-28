from pathlib import PurePosixPath

import tree_sitter_python
from tree_sitter import Language, Node, Parser

from app.parsing.base import ExtractedSymbol, ImportRef, ParsedFile
from app.parsing.fallback import fallback_parsed_file


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _walk(node: Node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _call_name(node: Node, source: bytes) -> str | None:
    function = node.child_by_field_name("function")
    if function is None:
        return None
    if function.type == "identifier":
        return _text(function, source)
    if function.type == "attribute":
        attribute = function.child_by_field_name("attribute")
        return _text(attribute, source) if attribute is not None else None
    return None


class PythonTreeSitterParser:
    language = "python"

    def __init__(self) -> None:
        self._parser = Parser(Language(tree_sitter_python.language()))

    def parse(self, source: str, file_path: str) -> ParsedFile:
        try:
            source_bytes = source.encode("utf-8")
            tree = self._parser.parse(source_bytes)
            if tree.root_node.has_error:
                return fallback_parsed_file(source, file_path, self.language)

            symbols: list[ExtractedSymbol] = []
            imports: list[ImportRef] = []
            routes: list[dict[str, object]] = []

            def visit(node: Node, parent_class: str | None = None) -> None:
                actual = node
                decorators: list[str] = []
                if node.type == "decorated_definition":
                    decorators = [
                        _text(child, source_bytes)
                        for child in node.children
                        if child.type == "decorator"
                    ]
                    definition = next(
                        (
                            child
                            for child in node.children
                            if child.type in {"function_definition", "class_definition"}
                        ),
                        None,
                    )
                    if definition is None:
                        return
                    actual = definition

                current_class = parent_class
                if actual.type in {"function_definition", "class_definition"}:
                    name_node = actual.child_by_field_name("name")
                    if name_node is not None:
                        name = _text(name_node, source_bytes)
                        symbol_type = (
                            "CLASS"
                            if actual.type == "class_definition"
                            else "METHOD" if parent_class else "FUNCTION"
                        )
                        metadata: dict[str, object] = {}
                        if actual.type == "class_definition":
                            superclasses = actual.child_by_field_name("superclasses")
                            metadata["bases"] = (
                                [
                                    _text(child, source_bytes)
                                    for child in superclasses.named_children
                                    if child.type in {"identifier", "attribute"}
                                ]
                                if superclasses is not None
                                else []
                            )
                            current_class = name
                        else:
                            body = actual.child_by_field_name("body")
                            calls = []
                            direct_calls = []
                            references = []
                            if body is not None:
                                for descendant in _walk(body):
                                    if descendant.type == "call":
                                        called = _call_name(descendant, source_bytes)
                                        if called:
                                            calls.append(called)
                                            function = descendant.child_by_field_name("function")
                                            if function is not None and function.type == "identifier":
                                                direct_calls.append(called)
                                    elif descendant.type == "identifier":
                                        references.append(_text(descendant, source_bytes))
                            metadata["calls"] = sorted(set(calls))
                            metadata["direct_calls"] = sorted(set(direct_calls))
                            metadata["references"] = sorted(set(references))
                            api_routes = [
                                decorator
                                for decorator in decorators
                                if any(
                                    f".{method}(" in decorator
                                    for method in ("get", "post", "put", "patch", "delete")
                                )
                            ]
                            if api_routes:
                                metadata["api_routes"] = api_routes
                                routes.extend(
                                    {"symbol": name, "decorator": route}
                                    for route in api_routes
                                )
                        symbols.append(
                            ExtractedSymbol(
                                name=name,
                                symbol_type=symbol_type,
                                start_line=node.start_point.row + 1,
                                end_line=node.end_point.row + 1,
                                parent_symbol=parent_class,
                                metadata=metadata,
                            )
                        )

                if actual.type in {"import_statement", "import_from_statement"}:
                    module_node = actual.child_by_field_name("module_name")
                    names = []
                    for name_node in actual.children_by_field_name("name"):
                        imported_name = name_node.child_by_field_name("name") or name_node
                        names.append(_text(imported_name, source_bytes))
                    if actual.type == "import_statement":
                        module = names[0] if names else _text(actual, source_bytes)
                    else:
                        module = _text(module_node, source_bytes) if module_node else ""
                    imports.append(
                        ImportRef(
                            module=module,
                            names=names,
                            start_line=actual.start_point.row + 1,
                            end_line=actual.end_point.row + 1,
                        )
                    )

                for child in actual.children:
                    if child.type in {
                        "function_definition",
                        "class_definition",
                        "decorated_definition",
                        "import_statement",
                        "import_from_statement",
                    }:
                        visit(child, current_class)
                    elif child.type == "block" and actual.type == "class_definition":
                        for member in child.children:
                            if member.type in {
                                "function_definition",
                                "class_definition",
                                "decorated_definition",
                            }:
                                visit(member, current_class)

            for child in tree.root_node.children:
                visit(child)

            name = PurePosixPath(file_path.replace("\\", "/")).name
            return ParsedFile(
                file_path=file_path.replace("\\", "/"),
                language=self.language,
                symbols=symbols,
                imports=imports,
                exports=[],
                parse_ok=True,
                fallback_used=False,
                metadata={
                    "is_test_file": name.startswith("test_") or name.endswith("_test.py"),
                    "api_routes": routes,
                },
            )
        except Exception:
            return fallback_parsed_file(source, file_path, self.language)
