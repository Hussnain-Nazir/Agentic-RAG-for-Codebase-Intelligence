import re

from pydantic import BaseModel

from app.tools.schemas import ArchitectureSummary
from app.validation.schema_validation import SchemaValidationError


class ArchitectureNarration(BaseModel):
    summary: str


class ArchitectureValidationError(SchemaValidationError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


_FILE_NAME = re.compile(r"(?<![\w])([\w.-]+\.(?:py|js|jsx|ts|tsx|json|md|yaml|yml|toml|txt|pdf))\b", re.IGNORECASE)
_PATH = re.compile(r"(?<![\w])([\w.-]+(?:/[\w.-]+)+/?)")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
_FOLDER_BEFORE = re.compile(r"(?<![\w./])([\w.-]+(?:/[\w.-]+)*)\s+(?:folder|directory)\b", re.IGNORECASE)
_FRAMEWORK_BEFORE = re.compile(r"\b([A-Za-z][\w.+-]*)\s+(?:framework|library)\b", re.IGNORECASE)
_NAMED_COMPONENT = re.compile(r"\b([A-Z][a-z][A-Za-z0-9_]*)\s+(?:model|service|component|class)\b")
_DETECTED_NAME = re.compile(r"\b([A-Z][A-Za-z0-9.+-]*)\s+is\s+detected\b")
_USED_TECHNOLOGY = re.compile(r"\b(?i:uses|built with|powered by|backed by)\s+([A-Z][A-Za-z0-9.+-]*)\b")
_KNOWN_FRAMEWORKS = {
    "angular", "django", "express", "fastapi", "flask", "nestjs",
    "next.js", "react", "svelte", "vite", "vue",
}
_KNOWN_LANGUAGES = {"python", "javascript", "typescript", "jsx", "tsx", "documentation"}
_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12,
}


def validate_architecture_summary(text: str, summary: ArchitectureSummary) -> None:
    """Reject named architecture facts absent from the inspected summary."""
    if not text.strip() or len(text) > 1_600:
        raise ArchitectureValidationError("length", "Architecture summary must be concise and nonempty")
    normalized = text.replace("\\", "/")
    allowed_paths = (
        set(summary.likely_entrypoints) | set(summary.test_locations)
        | set(summary.database_locations) | set(summary.api_locations)
        | set(summary.auth_locations)
    )
    allowed_folders = set(summary.top_level_folders)
    if summary.api_organization:
        allowed_folders.add(summary.api_organization)
    for path in allowed_paths:
        parts = path.split("/")
        allowed_folders.update("/".join(parts[:index]) for index in range(1, len(parts)))
    allowed_names = allowed_paths | allowed_folders
    allowed_file_names = {path.rsplit("/", 1)[-1] for path in allowed_paths}
    allowed_frameworks = {name.lower() for name in summary.frameworks_detected}
    allowed_languages = {name.lower() for name in summary.languages}
    allowed_numbers = set(summary.languages.values()) | {summary.repository_index_version}

    slash_names = {name.lower() for name in summary.top_level_folders} | allowed_frameworks | allowed_languages
    for match in _PATH.finditer(normalized):
        path = match.group(1).removeprefix("./")
        if path in allowed_names:
            continue
        without_slash = path.rstrip("/")
        if without_slash in allowed_names or all(
            part.lower() in slash_names for part in without_slash.split("/")
        ):
            continue
        without_punctuation = path.rstrip(".,;:!?")
        if without_punctuation != path and without_punctuation.rstrip("/") in allowed_names:
            continue
        raise ArchitectureValidationError("unknown_path",
            f"Architecture summary contains a path absent from inspect_repository: {path}"
        )
    for match in _FILE_NAME.finditer(normalized):
        name = match.group(1)
        if name not in allowed_file_names:
            raise ArchitectureValidationError("unknown_file",
                f"Architecture summary contains a file absent from inspect_repository: {name}"
            )
    for match in _FOLDER_BEFORE.finditer(normalized):
        name = match.group(1)
        if name.lower() not in {"top-level", "repository", "project", "source", "no", "application"} and name not in allowed_folders:
            raise ArchitectureValidationError("unknown_folder",
                f"Architecture summary contains a folder absent from inspect_repository: {name}"
            )
    for match in _FRAMEWORK_BEFORE.finditer(normalized):
        name = match.group(1)
        if name.lower() not in allowed_frameworks and name.lower() not in {
            "web", "backend", "frontend", "application", "database", "ui"
        }:
            raise ArchitectureValidationError("unknown_framework",
                f"Architecture summary contains a framework absent from inspect_repository: {name}"
            )
    for name in _KNOWN_FRAMEWORKS:
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", normalized, re.IGNORECASE) and name not in allowed_frameworks:
            raise ArchitectureValidationError("unknown_framework",
                f"Architecture summary contains a framework absent from inspect_repository: {name}"
            )
    for name in _KNOWN_LANGUAGES:
        if re.search(rf"(?<![\w./]){re.escape(name)}(?![\w])", normalized, re.IGNORECASE) and name not in allowed_languages:
            raise ArchitectureValidationError("unknown_language",
                f"Architecture summary contains a language absent from inspect_repository: {name}"
            )
    for match in _DETECTED_NAME.finditer(normalized):
        name = match.group(1)
        if name.lower() not in allowed_frameworks | allowed_languages:
            raise ArchitectureValidationError("unknown_detected_name",
                f"Architecture summary claims an uninspected detected name: {name}"
            )
    for match in _USED_TECHNOLOGY.finditer(normalized):
        name = match.group(1)
        if name.lower() in {"a", "an", "the"}:
            continue
        if name.lower() not in allowed_frameworks | allowed_languages:
            raise ArchitectureValidationError("unknown_technology",
                f"Architecture summary claims an uninspected technology: {name}"
            )
    for match in _NAMED_COMPONENT.finditer(normalized):
        name = match.group(0)
        if match.group(1) not in allowed_names:
            raise ArchitectureValidationError("unknown_component",
                f"Architecture summary contains a name absent from inspect_repository: {name}"
            )
    for match in _NUMBER.finditer(normalized):
        if match.group(0) not in {str(number) for number in allowed_numbers}:
            raise ArchitectureValidationError("unknown_number",
                f"Architecture summary contains a number absent from inspect_repository: {match.group(0)}"
            )
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", normalized, re.IGNORECASE) and value not in allowed_numbers:
            raise ArchitectureValidationError("unknown_number",
                f"Architecture summary contains a number absent from inspect_repository: {word}"
            )
