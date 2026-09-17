import fnmatch
from pathlib import PurePosixPath

from app.config import get_settings
from app.models.repository_file import RepositoryFileStatus

EXCLUDED_DIRECTORIES = {
    ".git",
    ".next",
    ".turbo",
    ".cache",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}
SECRET_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa*",
    "*.p12",
    "credentials.json",
    "secrets.*",
)
BINARY_EXTENSIONS = {
    ".7z",
    ".a",
    ".avi",
    ".bin",
    ".bmp",
    ".class",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".tar",
    ".tgz",
    ".wav",
    ".webp",
    ".zip",
}


def _normalize(path: str) -> str:
    normalized = path.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _matches_gitignore(path: str, patterns: list[str]) -> bool:
    ignored = False
    normalized = _normalize(path)
    for raw_pattern in patterns:
        pattern = raw_pattern.strip()
        if not pattern or pattern.startswith("#"):
            continue
        negate = pattern.startswith("!")
        if negate:
            pattern = pattern[1:]
        anchored = pattern.startswith("/")
        pattern = pattern.lstrip("/")
        directory_pattern = pattern.endswith("/")
        pattern = pattern.rstrip("/")
        candidates = [normalized] if anchored else [normalized, *PurePosixPath(normalized).parts]
        matched = any(
            fnmatch.fnmatch(candidate, pattern)
            or fnmatch.fnmatch(candidate, f"{pattern}/*")
            or (directory_pattern and candidate.startswith(f"{pattern}/"))
            for candidate in candidates
        )
        if matched:
            ignored = not negate
    return ignored


def is_ignored_path(path: str, gitignore_patterns: list[str] | None = None) -> bool:
    normalized = _normalize(path)
    parts = PurePosixPath(normalized).parts
    if ".." in parts:
        return True
    if any(part in EXCLUDED_DIRECTORIES or part.endswith(".egg-info") for part in parts):
        return True
    return bool(gitignore_patterns and _matches_gitignore(normalized, gitignore_patterns))


def is_secret_file(path: str) -> bool:
    name = PurePosixPath(_normalize(path)).name.lower()
    return any(fnmatch.fnmatch(name, pattern.lower()) for pattern in SECRET_PATTERNS)


def is_binary(content_bytes: bytes, path: str | None = None) -> bool:
    if path and PurePosixPath(_normalize(path)).suffix.lower() in BINARY_EXTENSIONS:
        return True
    return b"\x00" in content_bytes[:8192]


def classify_file(path: str, content_bytes: bytes) -> RepositoryFileStatus:
    if len(content_bytes) > get_settings().max_file_size_mb * 1024 * 1024:
        return RepositoryFileStatus.OVERSIZED
    if is_binary(content_bytes, path):
        return RepositoryFileStatus.BINARY
    return RepositoryFileStatus.OK
