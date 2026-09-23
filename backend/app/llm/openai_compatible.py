from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel

from app.llm.base import LLMResult, Message


def _strict_json_schema(value: Any) -> Any:
    """Return a strict transport schema without changing local Pydantic models."""
    if isinstance(value, dict):
        result = {key: _strict_json_schema(item) for key, item in value.items()}
        if result.get("title") == "Evidence":
            application_metadata = {
                "relationship_metadata",
                "retrieval_metadata",
                "external_source_metadata",
            }
            result["properties"] = {
                key: item
                for key, item in result.get("properties", {}).items()
                if key not in application_metadata
            }
            result["required"] = [
                key
                for key in result.get("required", [])
                if key not in application_metadata
            ]
        if result.get("type") == "object" or "properties" in result:
            result["additionalProperties"] = False
        return result
    if isinstance(value, list):
        return [_strict_json_schema(item) for item in value]
    return value


class OpenAICompatibleProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        timeout_s: int = 60,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not name or not base_url or not api_key:
            raise ValueError("Model name, base URL, and API key are required")
        self.model_name = name
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._transport = transport

    async def complete(
        self,
        messages: list[Message],
        schema: type[BaseModel] | None,
        timeout_s: int,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
        if schema is not None:
            schema_value = _strict_json_schema(schema.model_json_schema())
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema_value,
                    "strict": True,
                },
            }

        effective_timeout = timeout_s if timeout_s > 0 else self._timeout_s
        started_at = perf_counter()
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=effective_timeout,
        ) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        latency_ms = round((perf_counter() - started_at) * 1000)

        raw_response = response.json()
        content = self._extract_content(raw_response)
        usage = raw_response.get("usage") or {}
        return LLMResult(
            content=content,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            latency_ms=latency_ms,
            raw_response=raw_response,
        )

    @staticmethod
    def _extract_content(raw_response: dict[str, Any]) -> str:
        try:
            content = raw_response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Model response did not contain message content") from exc
        if not isinstance(content, str):
            raise ValueError("Model response content must be text")
        return content
