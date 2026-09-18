import asyncio
from typing import Any

from app.config import Settings, get_settings
from app.embeddings.base import EmbeddingProvider


class LocalEmbeddingProvider(EmbeddingProvider):
    """Local sentence-transformers embedding provider."""

    dimensions = 384
    batch_size = 32

    def __init__(
        self,
        model_name: str | None = None,
        *,
        settings: Settings | None = None,
        model: Any | None = None,
    ) -> None:
        configured = settings or get_settings()
        self.model_name = model_name or configured.embedding_model_name
        if model is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self.model_name)
        self._model = model
        model_dimensions = self._model.get_sentence_embedding_dimension()
        if model_dimensions != self.dimensions:
            raise ValueError(
                f"Embedding model must produce {self.dimensions} dimensions, "
                f"got {model_dimensions}"
            )

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            encoded = await asyncio.to_thread(
                self._model.encode,
                batch,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            for vector in encoded:
                values = [float(value) for value in vector]
                if len(values) != self.dimensions:
                    raise ValueError(
                        f"Embedding model returned {len(values)} dimensions, "
                        f"expected {self.dimensions}"
                    )
                vectors.append(values)
        return vectors
