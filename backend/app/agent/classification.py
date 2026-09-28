import enum
import re

from app.plugins.web_search.tool import is_external_doc_query


class TaskType(str, enum.Enum):
    DIRECT_FILE_OP = "DIRECT_FILE_OP"
    SYMBOL_LOOKUP = "SYMBOL_LOOKUP"
    REFERENCE_LOOKUP = "REFERENCE_LOOKUP"
    REPOSITORY_QA = "REPOSITORY_QA"
    ARCHITECTURE_EXPLANATION = "ARCHITECTURE_EXPLANATION"
    FLOW_TRACE = "FLOW_TRACE"
    CHANGE_IMPACT = "CHANGE_IMPACT"
    EXTERNAL_DOC_QUERY = "EXTERNAL_DOC_QUERY"


SUPPORTED_PATH_PATTERN = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:py|js|jsx|ts|tsx|json|md|yaml|yml|toml|txt|pdf))",
    re.IGNORECASE,
)
BARE_SYMBOL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FIND_SYMBOL_PATTERN = re.compile(
    r"^\s*(?:find|locate)\s+[`'\"]?(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)[`'\"]?\s*[?.]*\s*$",
    re.IGNORECASE,
)
REFERENCE_PATTERNS = (
    re.compile(
        r"where\s+is\s+[`'\"]?(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)[`'\"]?\s+(?:referenced|used)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:references|usages)\s+(?:to|of)\s+[`'\"]?(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)",
        re.IGNORECASE,
    ),
)
SYMBOL_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "does",
    "explain",
    "fastapi",
    "for",
    "from",
    "he",
    "her",
    "hers",
    "him",
    "his",
    "it",
    "its",
    "how",
    "include",
    "in",
    "me",
    "mine",
    "our",
    "ours",
    "she",
    "sqlalchemy",
    "show",
    "suppose",
    "the",
    "their",
    "theirs",
    "them",
    "they",
    "this",
    "to",
    "trace",
    "us",
    "we",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
    "you",
    "your",
    "yours",
}

MAX_REPOSITORY_SUBQUERIES = 6
_CLAUSE_BOUNDARY = re.compile(
    r"(?<=[?.;])\s+|,\s+(?=(?:and\s+)?(?:how|where|what|which)\b)|"
    r"\s+and\s+(?=(?:how|where|what|which)\b)",
    re.IGNORECASE,
)


def repository_subqueries(question: str) -> list[str]:
    """Split an explicit multi-part question without inventing new topics."""
    normalized = " ".join(question.strip().split())
    clauses = [part.strip(" ,;?.") for part in _CLAUSE_BOUNDARY.split(normalized)]
    meaningful = [part for part in clauses if len(re.findall(r"[A-Za-z_]+", part)) >= 3]
    if len(meaningful) <= 1:
        return []
    focused = list(meaningful)
    for clause in meaningful:
        match = re.search(
            r"\b([A-Za-z_]+)\s+are\b.+?\bfor\s+(?:the\s+)?(?:current\s+)?([A-Za-z_]+)\b",
            clause, re.IGNORECASE,
        )
        if match:
            owner_object = f"{match.group(2)} {match.group(1)}"
            if owner_object.lower() not in {item.lower() for item in focused}:
                focused.append(owner_object)
        current = re.search(r"\bcurrent\s+([A-Za-z_]+)\b", clause, re.IGNORECASE)
        if current:
            current_entity = f"current {current.group(1)}"
            if current_entity.lower() not in {item.lower() for item in focused}:
                focused.append(current_entity)
    return focused[:MAX_REPOSITORY_SUBQUERIES]


def is_identifier_shaped_symbol(value: str, source_text: str = "") -> bool:
    if not BARE_SYMBOL_PATTERN.fullmatch(value) or value.lower() in SYMBOL_STOPWORDS:
        return False
    quoted = re.search(rf"[`'\"]{re.escape(value)}[`'\"]", source_text)
    snake_case = "_" in value
    pascal_case = value[:1].isupper() and not value.isupper()
    camel_case = value[:1].islower() and any(character.isupper() for character in value[1:])
    return bool(quoted or snake_case or pascal_case or camel_case)


def extract_explicit_symbols(value: str) -> list[str]:
    symbols: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", value):
        candidate = match.group(0)
        if (
            candidate not in seen
            and is_identifier_shaped_symbol(candidate, value)
        ):
            seen.add(candidate)
            symbols.append(candidate)
    return symbols


def extract_file_path(value: str) -> str | None:
    match = SUPPORTED_PATH_PATTERN.search(value)
    return match.group("path") if match else None


def extract_reference_symbol(value: str) -> str | None:
    for pattern in REFERENCE_PATTERNS:
        match = pattern.search(value)
        if match:
            symbol = match.group("symbol")
            if is_identifier_shaped_symbol(symbol, value):
                return symbol
    return None


def extract_symbol(value: str) -> str | None:
    stripped = value.strip().strip("`'\"")
    if BARE_SYMBOL_PATTERN.fullmatch(stripped):
        return stripped
    match = FIND_SYMBOL_PATTERN.fullmatch(value)
    return match.group("symbol") if match else None


def classify_task(question_or_request: str) -> TaskType:
    value = " ".join(question_or_request.strip().split())
    lowered = value.lower()
    if is_external_doc_query(value):
        return TaskType.EXTERNAL_DOC_QUERY
    if lowered.startswith("trace ") or (
        "trace" in lowered and " from " in lowered and " to " in lowered
    ):
        return TaskType.FLOW_TRACE
    if any(
        phrase in lowered
        for phrase in (
            "what is affected",
            "what would be affected",
            "change impact",
            "impact of",
            "affected if",
        )
    ):
        return TaskType.CHANGE_IMPACT
    if any(
        phrase in lowered
        for phrase in (
            "explain the architecture",
            "repository architecture",
            "codebase architecture",
            "project structure",
        )
    ):
        return TaskType.ARCHITECTURE_EXPLANATION
    if extract_reference_symbol(value):
        return TaskType.REFERENCE_LOOKUP
    if extract_file_path(value) and any(
        lowered.startswith(prefix) for prefix in ("open ", "read ", "show ")
    ):
        return TaskType.DIRECT_FILE_OP
    if extract_symbol(value):
        return TaskType.SYMBOL_LOOKUP
    return TaskType.REPOSITORY_QA
