from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class LLMResult:
    content: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    raw_response: dict[str, Any]


class LLMProvider(Protocol):
    model_name: str

    async def complete(
        self,
        messages: list[Message],
        schema: type[BaseModel] | None,
        timeout_s: int,
    ) -> LLMResult: ...
