import uuid
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    repository_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None


class Tool(Protocol):
    name: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]
    requires_auth: bool

    async def execute(
        self,
        input: BaseModel,
        ctx: ExecutionContext,
    ) -> BaseModel: ...
