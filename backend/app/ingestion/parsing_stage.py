from pathlib import PurePosixPath

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_object_session

from app.models.code_relationship import CodeRelationship
from app.models.code_symbol import CodeSymbol
from app.models.repository_file import RepositoryFile, RepositoryFileStatus
from app.parsing.base import ParsedFile, TreeSitterParser
from app.parsing.fallback import fallback_parsed_file
from app.parsing.javascript_parser import JavaScriptTreeSitterParser
from app.parsing.python_parser import PythonTreeSitterParser
from app.parsing.relationships import MODULE_SYMBOL_NAME, extract_relationships
from app.parsing.typescript_parser import TypeScriptTreeSitterParser


def _parser_for(path: str) -> TreeSitterParser | None:
    suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
    if suffix == ".py":
        return PythonTreeSitterParser()
    if suffix == ".js":
        return JavaScriptTreeSitterParser()
    if suffix == ".jsx":
        return JavaScriptTreeSitterParser(jsx=True)
    if suffix == ".ts":
        return TypeScriptTreeSitterParser()
    if suffix == ".tsx":
        return TypeScriptTreeSitterParser(tsx=True)
    return None


async def parse_repository_files(files: list[RepositoryFile]) -> list[ParsedFile]:
    if not files:
        return []
    session = async_object_session(files[0])
    if session is None:
        raise ValueError("Repository files must be attached to an AsyncSession")

    index_ids = {item.repository_index_id for item in files}
    if len(index_ids) != 1:
        raise ValueError("Repository files must belong to one index version")
    repository_index_id = next(iter(index_ids))
    await session.execute(
        delete(CodeRelationship).where(
            CodeRelationship.repository_index_id == repository_index_id
        )
    )
    await session.execute(
        delete(CodeSymbol).where(CodeSymbol.repository_index_id == repository_index_id)
    )

    parsed_files: list[tuple[RepositoryFile, ParsedFile]] = []
    for file in files:
        if file.status is not RepositoryFileStatus.OK or file.content is None:
            continue
        parser = _parser_for(file.path)
        if parser is None:
            continue
        try:
            parsed = parser.parse(file.content, file.path)
        except Exception:
            parsed = fallback_parsed_file(file.content, file.path, file.language)
        if not parsed.parse_ok:
            file.status = RepositoryFileStatus.PARSE_FAILED
        parsed_files.append((file, parsed))

    symbol_rows: dict[tuple[object, str], CodeSymbol] = {}
    symbols_by_name: dict[str, list[CodeSymbol]] = {}
    for file, parsed in parsed_files:
        if not parsed.parse_ok:
            continue
        if parsed.imports:
            module_row = CodeSymbol(
                repository_index_id=repository_index_id,
                file_id=file.id,
                name=MODULE_SYMBOL_NAME,
                symbol_type="MODULE",
                start_line=1,
                end_line=max(len((file.content or "").splitlines()), 1),
            )
            session.add(module_row)
            symbol_rows[(file.id, MODULE_SYMBOL_NAME)] = module_row
        for symbol in parsed.symbols:
            row = CodeSymbol(
                repository_index_id=repository_index_id,
                file_id=file.id,
                name=symbol.name,
                symbol_type=symbol.symbol_type,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                parent_symbol=symbol.parent_symbol,
            )
            session.add(row)
            symbol_rows[(file.id, symbol.name)] = row
            symbols_by_name.setdefault(symbol.name, []).append(row)
    await session.flush()

    for file, parsed in parsed_files:
        if not parsed.parse_ok:
            continue
        for extracted in extract_relationships(parsed):
            source = symbol_rows.get((file.id, extracted.from_symbol))
            if source is None:
                continue
            target = symbol_rows.get((file.id, extracted.to_symbol))
            if target is None and extracted.to_symbol:
                candidates = symbols_by_name.get(extracted.to_symbol, [])
                target = candidates[0] if len(candidates) == 1 else None
            session.add(
                CodeRelationship(
                    repository_index_id=repository_index_id,
                    from_symbol_id=source.id,
                    to_symbol_id=target.id if target else None,
                    kind=extracted.kind,
                    confidence=extracted.confidence,
                )
            )
    await session.flush()
    return [parsed for _, parsed in parsed_files]
