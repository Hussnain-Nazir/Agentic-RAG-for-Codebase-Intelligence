import re

from pydantic import BaseModel

from app.tools.schemas import ArchitectureSummary
from app.validation.schema_validation import SchemaValidationError


class ArchitectureNarration(BaseModel):
    summary: str


_FILE_NAME = re.compile(r"(?<![\w])([\w.-]+\.(?:py|js|jsx|ts|tsx|json|md|yaml|yml|toml|txt|pdf))\b", re.IGNORECASE)
_PATH = re.compile(r"(?<![\w])([\w.-]+(?:/[\w.-]+)+/?)")
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
_FOLDER_BEFORE = re.compile(r"\b([\w.-]+)\s+(?:folder|directory)\b", re.IGNORECASE)
_FOLDER_SLASH = re.compile(r"(?<![\w./])([A-Za-z][\w.-]*)/(?![\w])")
_FRAMEWORK_BEFORE = re.compile(r"\b([A-Za-z][\w.+-]*)\s+(?:framework|library)\b", re.IGNORECASE)
_FOLDER_LIST = re.compile(r"\b(?:folders?|directories)\s+(?:are|include|:)\s+([^.;]+)", re.IGNORECASE)
_FRAMEWORK_LIST = re.compile(r"\bframeworks?\s+(?:are|include|detected|:)\s+([^.;]+)", re.IGNORECASE)
_KNOWN_FRAMEWORKS = {
    "angular", "django", "express", "fastapi", "flask", "nestjs",
    "next.js", "react", "svelte", "vite", "vue",
}
_KNOWN_LANGUAGES = {"python", "javascript", "typescript", "jsx", "tsx", "documentation"}
_GENERIC_CAPITALIZED = {
    "a", "an", "and", "api", "at", "its", "it", "no", "the", "there",
    "this", "top-level", "none",
}
_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12,
}


def validate_architecture_summary(text: str, summary: ArchitectureSummary) -> None:
    """Reject named architecture facts absent from the inspected summary."""
    if not text.strip() or len(text) > 800:
        raise SchemaValidationError("Architecture summary must be concise and nonempty")
    allowed_paths = (
        set(summary.likely_entrypoints) | set(summary.test_locations)
        | set(summary.database_locations) | set(summary.api_locations)
        | set(summary.auth_locations)
    )
    allowed_folders = set(summary.top_level_folders)
    if summary.api_organization:
        allowed_folders.add(summary.api_organization)
    allowed_names = allowed_paths | allowed_folders
    allowed_frameworks = {name.lower() for name in summary.frameworks_detected}
    allowed_languages = {name.lower() for name in summary.languages}
    allowed_numbers = set(summary.languages.values()) | {summary.repository_index_version}

    for match in _PATH.finditer(text):
        path = match.group(1).rstrip("/")
        if path not in allowed_names and match.group(1) not in allowed_paths:
            raise SchemaValidationError(
                f"Architecture summary contains a path absent from inspect_repository: {path}"
            )
    for match in _FILE_NAME.finditer(text):
        if match.start() > 0 and text[match.start() - 1] == "/":
            continue
        name = match.group(1)
        if name not in allowed_paths:
            raise SchemaValidationError(
                f"Architecture summary contains a file absent from inspect_repository: {name}"
            )
    for match in _FOLDER_BEFORE.finditer(text):
        name = match.group(1)
        if name.lower() not in {"top-level", "repository", "project", "source", "no"} and name not in allowed_folders:
            raise SchemaValidationError(
                f"Architecture summary contains a folder absent from inspect_repository: {name}"
            )
    for match in _FOLDER_SLASH.finditer(text):
        name = match.group(1)
        if name not in allowed_folders:
            raise SchemaValidationError(
                f"Architecture summary contains a folder absent from inspect_repository: {name}"
            )
    for match in _FOLDER_LIST.finditer(text):
        for name in re.split(r",|\band\b", match.group(1)):
            name = name.strip(" `\"'/")
            if name and name not in allowed_folders:
                raise SchemaValidationError(
                    f"Architecture summary contains a folder absent from inspect_repository: {name}"
                )
    for match in _FRAMEWORK_LIST.finditer(text):
        phrase = match.group(1).strip()
        if phrase.lower().startswith(("not ", "none", "no ")):
            continue
        for name in re.split(r",|\band\b", phrase):
            name = name.strip(" `\"'")
            if name and name.lower() not in allowed_frameworks:
                raise SchemaValidationError(
                    f"Architecture summary contains a framework absent from inspect_repository: {name}"
                )
    for match in _FRAMEWORK_BEFORE.finditer(text):
        name = match.group(1)
        if name.lower() not in allowed_frameworks and name.lower() not in {
            "web", "backend", "frontend", "application"
        }:
            raise SchemaValidationError(
                f"Architecture summary contains a framework absent from inspect_repository: {name}"
            )
    for name in _KNOWN_FRAMEWORKS:
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text, re.IGNORECASE) and name not in allowed_frameworks:
            raise SchemaValidationError(
                f"Architecture summary contains a framework absent from inspect_repository: {name}"
            )
    for name in _KNOWN_LANGUAGES:
        if re.search(rf"(?<![\w]){re.escape(name)}(?![\w])", text, re.IGNORECASE) and name not in allowed_languages:
            raise SchemaValidationError(
                f"Architecture summary contains a language absent from inspect_repository: {name}"
            )
    for match in re.finditer(r"\b[A-Z][A-Za-z0-9.+-]*\b", text):
        name = match.group(0)
        if (
            name.lower() not in _GENERIC_CAPITALIZED
            and name.lower() not in allowed_frameworks
            and name.lower() not in allowed_languages
            and name not in allowed_names
        ):
            raise SchemaValidationError(
                f"Architecture summary contains a name absent from inspect_repository: {name}"
            )
    for match in _NUMBER.finditer(text):
        if match.group(0) not in {str(number) for number in allowed_numbers}:
            raise SchemaValidationError(
                f"Architecture summary contains a number absent from inspect_repository: {match.group(0)}"
            )
    for word, value in _NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text, re.IGNORECASE) and value not in allowed_numbers:
            raise SchemaValidationError(
                f"Architecture summary contains a number absent from inspect_repository: {word}"
            )
