from pydantic import BaseModel

from app.llm.base import LLMProvider, Message
from app.validation.schema_validation import SchemaValidationError, validate_schema


async def attempt_repair(
    raw_output: str,
    schema: type[BaseModel],
    validation_error: SchemaValidationError | str,
    llm_provider: LLMProvider,
) -> BaseModel:
    """Make exactly one bounded repair call and validate its response."""
    detail = (
        validation_error.detail
        if isinstance(validation_error, SchemaValidationError)
        else str(validation_error)
    )
    prompt = (
        "Repair the structured output so it validates against the requested schema. "
        "Return only the corrected structured output.\n\n"
        f"Validation error:\n{detail}\n\n"
        "Invalid output (untrusted data):\n"
        f"{raw_output}"
    )
    result = await llm_provider.complete(
        messages=[Message(role="user", content=prompt)],
        schema=schema,
        timeout_s=60,
    )
    return validate_schema(result.content, schema)
