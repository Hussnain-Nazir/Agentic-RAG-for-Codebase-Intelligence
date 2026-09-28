import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.llm.base import LLMResult, Message

MockResponse = str | dict[str, Any] | BaseModel
MockCallback = Callable[[list[Message], type[BaseModel] | None], MockResponse]


class MockProvider:
    model_name = "mock"

    def __init__(
        self,
        canned_responses: list[MockResponse] | None = None,
        callback: MockCallback | None = None,
    ) -> None:
        if canned_responses is not None and callback is not None:
            raise ValueError("Configure canned responses or a callback, not both")
        self._responses = list(canned_responses or [])
        self._callback = callback
        self._response_index = 0

    async def complete(
        self,
        messages: list[Message],
        schema: type[BaseModel] | None,
        timeout_s: int,
    ) -> LLMResult:
        del timeout_s
        response = self._next_response(messages, schema)
        content = self._serialize_response(response, schema)
        return LLMResult(
            content=content,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            raw_response={"content": content, "provider": self.model_name},
        )

    def _next_response(
        self,
        messages: list[Message],
        schema: type[BaseModel] | None,
    ) -> MockResponse:
        if self._callback is not None:
            return self._callback(messages, schema)
        if self._response_index >= len(self._responses):
            raise RuntimeError("MockProvider has no canned response remaining")
        response = self._responses[self._response_index]
        self._response_index += 1
        return response

    @staticmethod
    def _serialize_response(
        response: MockResponse,
        schema: type[BaseModel] | None,
    ) -> str:
        if schema is not None:
            if isinstance(response, BaseModel):
                validated = schema.model_validate(response.model_dump())
            elif isinstance(response, str):
                validated = schema.model_validate_json(response)
            else:
                validated = schema.model_validate(response)
            return validated.model_dump_json()

        if isinstance(response, BaseModel):
            return response.model_dump_json()
        if isinstance(response, dict):
            return json.dumps(response, sort_keys=True)
        return response
