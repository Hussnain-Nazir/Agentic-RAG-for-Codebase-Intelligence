import re
from pathlib import PurePosixPath

import tree_sitter_javascript
from tree_sitter import Language, Node, Parser

from app.parsing.base import ExtractedSymbol, ImportRef, ParsedFile
from app.parsing.fallback import fallback_parsed_file

HOOK_NAME = re.compile(r"^use[A-Z]")


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _walk(node: Node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _contains_jsx(node: Node) -> bool:
    return any(
        descendant.type in {"jsx_element", "jsx_self_closing_element", "jsx_fragment"}
        for descendant in _walk(node)
    )


def _callee_name(node: Node, source: bytes) -> str | None:
    function = node.child_by_field_name("function")
    if function is None:
        return None
    if function.type == "identifier":
        return _text(function, source)
    if function.type in {"member_expression", "subscript_expression"}:
        property_node = function.child_by_field_name("property")
        return _text(property_node, source) if property_node is not None else None
    return None


def _function_metadata(node: Node, source: bytes) -> dict[str, object]:
    calls: set[str] = set()
    references: set[str] = set()
    api_calls: list[str] = []
    for descendant in _walk(node):
        if descendant.type == "call_expression":
            called = _callee_name(descendant, source)
            if called:
                calls.add(called)
            function = descendant.child_by_field_name("function")
            function_text = _text(function, source) if function is not None else ""
            if function_text == "fetch" or function_text.startswith("axios."):
                arguments = descendant.child_by_field_name("arguments")
                if arguments is not None:
                    string_arg = next(
                        (child for child in arguments.named_children if child.type in {"string", "template_string"}),
                        None,
                    )
                    if string_arg is not None:
                        api_calls.append(_text(string_arg, source).strip("'\"`"))
        elif descendant.type == "identifier":
            references.add(_text(descendant, source))
    return {
        "calls": sorted(calls),
        "references": sorted(references),
        "api_calls": api_calls,
    }


def _parse_ecmascript(
    parser: Parser,
    source: str,
    file_path: str,
    language: str,
) -> ParsedFile:
    try:
        source_bytes = source.encode("utf-8")
        tree = parser.parse(source_bytes)
        if tree.root_node.has_error:
            return fallback_parsed_file(source, file_path, language)

        symbols: list[ExtractedSymbol] = []
        imports: list[ImportRef] = []
        exports: list[str] = []
        routes: list[dict[str, object]] = []

        def add_symbol(node: Node, name: str, symbol_type: str, parent: str | None = None) -> None:
            metadata: dict[str, object] = {}
            if symbol_type in {"FUNCTION", "METHOD", "COMPONENT", "HOOK"}:
                metadata = _function_metadata(node, source_bytes)
            if symbol_type == "CLASS":
                metadata["bases"] = [
                    _text(item, source_bytes)
                    for descendant in node.named_children
                    if descendant.type in {"class_heritage", "extends_clause"}
                    for item in descendant.named_children
                    if item.type in {"identifier", "type_identifier"}
                ]
            symbols.append(
                ExtractedSymbol(
                    name=name,
                    symbol_type=symbol_type,
                    start_line=node.start_point.row + 1,
                    end_line=node.end_point.row + 1,
                    parent_symbol=parent,
                    metadata=metadata,
                )
            )

        def visit(node: Node, parent_class: str | None = None, exported: bool = False) -> None:
            if node.type == "export_statement":
                declaration = node.child_by_field_name("declaration")
                if declaration is not None:
                    visit(declaration, parent_class, True)
                else:
                    for child in node.named_children:
                        if child.type == "export_clause":
                            exports.extend(
                                _text(item.child_by_field_name("name") or item, source_bytes)
                                for item in child.named_children
                            )
                return

            if node.type in {"function_declaration", "generator_function_declaration"}:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    name = _text(name_node, source_bytes)
                    symbol_type = "HOOK" if HOOK_NAME.match(name) else "COMPONENT" if name[:1].isupper() and _contains_jsx(node) else "FUNCTION"
                    add_symbol(node, name, symbol_type, parent_class)
                    if exported:
                        exports.append(name)
            elif node.type == "class_declaration":
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    name = _text(name_node, source_bytes)
                    add_symbol(node, name, "CLASS", parent_class)
                    if exported:
                        exports.append(name)
                    for descendant in node.named_children:
                        if descendant.type == "class_body":
                            for method in descendant.named_children:
                                if method.type == "method_definition":
                                    method_name = method.child_by_field_name("name")
                                    if method_name is not None:
                                        add_symbol(method, _text(method_name, source_bytes), "METHOD", name)
            elif node.type in {"interface_declaration", "type_alias_declaration"}:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    name = _text(name_node, source_bytes)
                    add_symbol(node, name, "INTERFACE" if node.type == "interface_declaration" else "TYPE")
                    if node.type == "interface_declaration":
                        symbols[-1].metadata["bases"] = [
                            _text(item, source_bytes)
                            for descendant in node.named_children
                            if descendant.type == "extends_type_clause"
                            for item in descendant.named_children
                            if item.type in {"identifier", "type_identifier"}
                        ]
                    if exported:
                        exports.append(name)
            elif node.type in {"lexical_declaration", "variable_declaration"}:
                for declarator in node.named_children:
                    if declarator.type != "variable_declarator":
                        continue
                    name_node = declarator.child_by_field_name("name")
                    value = declarator.child_by_field_name("value")
                    if name_node is None or value is None or value.type not in {"arrow_function", "function_expression"}:
                        continue
                    name = _text(name_node, source_bytes)
                    symbol_type = "HOOK" if HOOK_NAME.match(name) else "COMPONENT" if name[:1].isupper() and _contains_jsx(value) else "FUNCTION"
                    add_symbol(declarator, name, symbol_type, parent_class)
                    if exported:
                        exports.append(name)
            elif node.type == "import_statement":
                source_node = node.child_by_field_name("source")
                module = _text(source_node, source_bytes).strip("'\"") if source_node else ""
                names = []
                import_clause = next(
                    (child for child in node.named_children if child.type == "import_clause"),
                    None,
                )
                for descendant in _walk(import_clause) if import_clause is not None else []:
                    if descendant.type == "import_specifier":
                        name_node = descendant.child_by_field_name("name") or descendant.named_child(0)
                        if name_node is not None:
                            names.append(_text(name_node, source_bytes))
                    elif descendant.type == "identifier" and descendant.parent.type in {
                        "import_clause",
                        "namespace_import",
                    }:
                        names.append(_text(descendant, source_bytes))
                imports.append(
                    ImportRef(
                        module=module,
                        names=names,
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                    )
                )
            elif node.type == "expression_statement":
                text = _text(node, source_bytes)
                match = re.search(r"\b(?:app|router)\.(get|post|put|patch|delete)\s*\(\s*(['\"])(.*?)\2", text)
                if match:
                    routes.append({"method": match.group(1).upper(), "path": match.group(3), "line": node.start_point.row + 1})

        for child in tree.root_node.children:
            visit(child)

        name = PurePosixPath(file_path.replace("\\", "/")).name
        return ParsedFile(
            file_path=file_path.replace("\\", "/"),
            language=language,
            symbols=symbols,
            imports=imports,
            exports=sorted(set(exports)),
            parse_ok=True,
            fallback_used=False,
            metadata={
                "is_test_file": bool(re.search(r"\.(?:test|spec)\.[jt]sx?$", name)),
                "api_routes": routes,
            },
        )
    except Exception:
        return fallback_parsed_file(source, file_path, language)


class JavaScriptTreeSitterParser:
    def __init__(self, jsx: bool = False) -> None:
        self.language = "jsx" if jsx else "javascript"
        self._parser = Parser(Language(tree_sitter_javascript.language()))

    def parse(self, source: str, file_path: str) -> ParsedFile:
        return _parse_ecmascript(self._parser, source, file_path, self.language)
