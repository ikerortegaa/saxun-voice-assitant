"""
Servicio de embeddings usando OpenAI text-embedding-3-small.
Modelo elegido por relación calidad/precio: $0.02/1M tokens.
"""
import asyncio
from typing import Optional
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from src.config import get_settings


class EmbeddingService:
    """Genera embeddings con OpenAI text-embedding-3-small."""

    def __init__(self):
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_embedding_model
        self._dimensions = settings.openai_embedding_dimensions

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def embed_text(self, text: str) -> list[float]:
        """Genera embedding para un texto."""
        text = text.replace("\n", " ").strip()
        if not text:
            return [0.0] * self._dimensions

        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dimensions,
        )
        return response.data[0].embedding

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
    )
    async def embed_batch(self, texts: list[str], batch_size: int = 100) -> list[list[float]]:
        """
        Genera embeddings para múltiples textos en lotes.
        Óptimo para ingestión de documentos.
        """
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = [t.replace("\n", " ").strip() for t in texts[i:i + batch_size]]
            # Filtrar textos vacíos
            batch = [t if t else " " for t in batch]

            logger.debug(f"Embebiendo lote {i // batch_size + 1}: {len(batch)} textos")
            response = await self._client.embeddings.create(
                model=self._model,
                input=batch,
                dimensions=self._dimensions,
            )
            embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(embeddings)

            # Pausa breve para evitar rate limiting
            if i + batch_size < len(texts):
                await asyncio.sleep(0.1)

        return all_embeddings

    @property
    def dimensions(self) -> int:
        return self._dimensions
