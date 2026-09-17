from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel

from app.llm.base import LLMResult, Message


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
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema.model_json_schema(),
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
