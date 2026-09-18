from typing import Protocol


class EmbeddingProvider(Protocol):
    dimensions: int

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts in input order."""
        ...
