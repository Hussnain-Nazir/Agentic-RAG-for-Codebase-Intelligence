from pathlib import PurePosixPath

from app.parsing.base import ParsedFile

LANGUAGE_BY_SUFFIX = {
    ".js": "javascript",
    ".jsx": "jsx",
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
}


def fallback_parsed_file(
    source: str,
    file_path: str,
    language: str | None = None,
) -> ParsedFile:
    try:
        detected = language or LANGUAGE_BY_SUFFIX.get(
            PurePosixPath(file_path.replace("\\", "/")).suffix.lower(),
            "unknown",
        )
        line_count = max(len(source.splitlines()), 1)
        return ParsedFile(
            file_path=file_path.replace("\\", "/"),
            language=detected,
            symbols=[],
            imports=[],
            exports=[],
            parse_ok=False,
            fallback_used=True,
            metadata={
                "chunk_type": "FALLBACK",
                "start_line": 1,
                "end_line": line_count,
            },
        )
    except Exception:
        return ParsedFile(
            file_path=str(file_path),
            language="unknown",
            symbols=[],
            imports=[],
            exports=[],
            parse_ok=False,
            fallback_used=True,
            metadata={"chunk_type": "FALLBACK", "start_line": 1, "end_line": 1},
        )
