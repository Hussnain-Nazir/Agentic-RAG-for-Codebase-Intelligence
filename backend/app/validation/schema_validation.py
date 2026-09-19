from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class SchemaValidationError(ValueError):
    def __init__(self, detail: str, *, errors: list[dict[str, Any]] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.errors = errors or []


def validate_schema(raw_output: Any, schema: type[SchemaT]) -> SchemaT:
    try:
        if isinstance(raw_output, schema):
            return raw_output
        if isinstance(raw_output, BaseModel):
            return schema.model_validate(raw_output.model_dump())
        if isinstance(raw_output, (str, bytes, bytearray)):
            return schema.model_validate_json(raw_output)
        return schema.model_validate(raw_output)
    except ValidationError as exc:
        raise SchemaValidationError(str(exc), errors=exc.errors()) from exc
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError(str(exc)) from exc
