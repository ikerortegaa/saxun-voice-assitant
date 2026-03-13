"""
Hybrid Retriever: Dense (pgvector) + Sparse (BM25) + RRF fusion + Re-ranking.
Arquitectura de retrieval de alta calidad para el RAG de Saxun.
"""
import time
from collections import defaultdict
from typing import Optional

import asyncpg
from loguru import logger

from src.config import get_settings
from src.models.rag_models import Chunk, RetrievalResult
from src.rag.embeddings import EmbeddingService


class HybridRetriever:
    """
    Búsqueda híbrida: combina similitud semántica (pgvector cosine)
    con búsqueda léxica (PostgreSQL full-text) usando RRF fusion.
    Opcionalmente aplica re-ranking con cross-encoder.
    """

    RRF_K = 60  # Constante RRF estándar

    def __init__(self, db_pool: asyncpg.Pool, use_reranker: bool = False):
        self._db = db_pool
        self._embedder = EmbeddingService()
        self._settings = get_settings()
        self._use_reranker = use_reranker
        self._reranker = None

        if use_reranker:
            self._load_reranker()

    def _load_reranker(self):
        """Carga el cross-encoder para re-ranking (opcional, más lento)."""
        try:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder(
                "cross-encoder/ms-marco-MiniLM-L-6-v2",
                max_length=512,
            )
            logger.info("Cross-encoder re-ranker cargado")
        except Exception as e:
            logger.warning(f"No se pudo cargar el re-ranker: {e}")
            self._use_reranker = False

    async def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        language: Optional[str] = None,
        sensitivity_level: str = "public",
        candidates_multiplier: int = 4,
    ) -> RetrievalResult:
        """
        Recupera los chunks más relevantes para la query.

        Args:
            query: Texto de búsqueda
            top_k: Número de chunks a devolver (default: settings)
            language: Filtrar por idioma (None = todos)
            sensitivity_level: Nivel máximo de sensibilidad accesible
            candidates_multiplier: Multiplicador de candidatos para RRF

        Returns:
            RetrievalResult con chunks ordenados por relevancia
        """
        k = top_k or self._settings.rag_top_k
        candidates = k * candidates_multiplier
        start = time.time()

        # 1. Embedding de la query
        query_embedding = await self._embedder.embed_text(query)

        # 2. Búsquedas en paralelo
        semantic_results, lexical_results = await self._parallel_search(
            query, query_embedding, candidates, language, sensitivity_level
        )

        # 3. Fusión RRF
        fused = self._reciprocal_rank_fusion(semantic_results, lexical_results)

        # 4. Recuperar contenido de los top candidatos
        top_ids = [chunk_id for chunk_id, _ in fused[:candidates]]
        chunks = await self._fetch_chunks_by_ids(top_ids, fused)

        # 5. Re-ranking opcional
        if self._use_reranker and self._reranker and len(chunks) > 1:
            chunks = self._rerank(query, chunks, k)
        else:
            chunks = chunks[:k]

        latency = (time.time() - start) * 1000
        logger.debug(
            f"Retrieval: query='{query[:50]}' → {len(chunks)} chunks "
            f"(semantic:{len(semantic_results)}, lexical:{len(lexical_results)}) "
            f"latency={latency:.0f}ms"
        )

        return RetrievalResult(
            chunks=chunks,
            query=query,
            method="hybrid" if semantic_results and lexical_results else "dense",
            latency_ms=latency,
        )

    # ── Búsquedas ────────────────────────────────────────────────────────────

    async def _parallel_search(
        self,
        query: str,
        query_embedding: list[float],
        candidates: int,
        language: Optional[str],
        sensitivity_level: str,
    ) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
        """Ejecuta búsqueda semántica y léxica en paralelo."""
        import asyncio

        semantic_task = asyncio.create_task(
            self._semantic_search(query_embedding, candidates, language, sensitivity_level)
        )
        lexical_task = asyncio.create_task(
            self._lexical_search(query, candidates, language, sensitivity_level)
        )

        semantic_results, lexical_results = await asyncio.gather(
            semantic_task, lexical_task, return_exceptions=True
        )

        # Manejar errores parciales
        if isinstance(semantic_results, Exception):
            logger.warning(f"Error en búsqueda semántica: {semantic_results}")
            semantic_results = []
        if isinstance(lexical_results, Exception):
            logger.warning(f"Error en búsqueda léxica: {lexical_results}")
            lexical_results = []

        return semantic_results, lexical_results

    async def _semantic_search(
        self,
        query_embedding: list[float],
        candidates: int,
        language: Optional[str],
        sensitivity_level: str,
    ) -> list[tuple[str, float]]:
        """Búsqueda semántica con pgvector (cosine similarity)."""
        import numpy as np
        embedding_vec = np.array(query_embedding, dtype=np.float32)
        allowed_sensitivity = self._get_allowed_sensitivity(sensitivity_level)

        query_sql = """
            SELECT chunk_id,
                   1 - (embedding <=> $1) AS score
            FROM chunks
            WHERE status = 'active'
              AND sensitivity = ANY($2::text[])
              AND ($3::text IS NULL OR language = $3)
              AND (
                  SELECT expiry_date IS NULL OR expiry_date > NOW()
                  FROM document_registry dr
                  WHERE dr.doc_id = chunks.doc_id
              )
            ORDER BY embedding <=> $1
            LIMIT $4
        """
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                query_sql,
                embedding_vec,
                allowed_sensitivity,
                language,
                candidates,
            )
        return [(row["chunk_id"], float(row["score"])) for row in rows]

    async def _lexical_search(
        self,
        query: str,
        candidates: int,
        language: Optional[str],
        sensitivity_level: str,
    ) -> list[tuple[str, float]]:
        """Búsqueda léxica con PostgreSQL full-text search."""
        allowed_sensitivity = self._get_allowed_sensitivity(sensitivity_level)
        # Escapar query para plainto_tsquery
        safe_query = query.replace("'", "''")
        config = "spanish" if language in (None, "es") else "simple"

        query_sql = """
            SELECT chunk_id,
                   ts_rank(
                       to_tsvector($1, content),
                       plainto_tsquery($1, $2)
                   ) AS score
            FROM chunks
            WHERE status = 'active'
              AND sensitivity = ANY($3::text[])
              AND ($4::text IS NULL OR language = $4)
              AND to_tsvector($1, content) @@ plainto_tsquery($1, $2)
              AND (
                  SELECT expiry_date IS NULL OR expiry_date > NOW()
                  FROM document_registry dr
                  WHERE dr.doc_id = chunks.doc_id
              )
            ORDER BY score DESC
            LIMIT $5
        """
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                query_sql,
                config,
                safe_query,
                allowed_sensitivity,
                language,
                candidates,
            )
        return [(row["chunk_id"], float(row["score"])) for row in rows]

    async def _fetch_chunks_by_ids(
        self,
        chunk_ids: list[str],
        fused_scores: list[tuple[str, float]],
    ) -> list[Chunk]:
        """Recupera el contenido completo de los chunks."""
        if not chunk_ids:
            return []

        score_map = {cid: score for cid, score in fused_scores}

        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT c.chunk_id, c.doc_id, c.content, c.section,
                       c.language, c.sensitivity, c.status, c.metadata,
                       dr.title as doc_title
                FROM chunks c
                JOIN document_registry dr ON c.doc_id = dr.doc_id
                WHERE c.chunk_id = ANY($1::text[])
                  AND c.status = 'active'
                """,
                chunk_ids,
            )

        chunks = []
        for row in rows:
            chunk_id = row["chunk_id"]
            import json as _json
            meta = _json.loads(row["metadata"]) if row["metadata"] else {}
            meta["doc_title"] = row["doc_title"]
            chunks.append(Chunk(
                chunk_id=chunk_id,
                doc_id=row["doc_id"],
                content=row["content"],
                section=row["section"] or "",
                language=row["language"],
                sensitivity=row["sensitivity"],
                status=row["status"],
                score=score_map.get(chunk_id, 0.0),
                metadata=meta,
            ))

        # Ordenar por score RRF
        chunks.sort(key=lambda c: c.score, reverse=True)
        return chunks

    # ── Algoritmos ───────────────────────────────────────────────────────────

    def _reciprocal_rank_fusion(
        self,
        semantic: list[tuple[str, float]],
        lexical: list[tuple[str, float]],
    ) -> list[tuple[str, float]]:
        """Fusiona rankings semántico y léxico con RRF."""
        scores: dict[str, float] = defaultdict(float)

        for rank, (chunk_id, _) in enumerate(semantic):
            scores[chunk_id] += 1.0 / (self.RRF_K + rank + 1)

        for rank, (chunk_id, _) in enumerate(lexical):
            scores[chunk_id] += 1.0 / (self.RRF_K + rank + 1)

        return sorted(scores.items(), key=lambda x: x[1], reverse=True)

    def _rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]:
        """Re-ranking con cross-encoder (más lento, más preciso)."""
        pairs = [(query, chunk.content) for chunk in chunks]
        try:
            scores = self._reranker.predict(pairs)
            ranked = sorted(
                zip(chunks, scores), key=lambda x: x[1], reverse=True
            )
            reranked = [chunk for chunk, _ in ranked[:top_k]]
            # Actualizar scores con los del reranker
            for chunk, score in zip(reranked, [s for _, s in ranked[:top_k]]):
                chunk.score = float(score)
            return reranked
        except Exception as e:
            logger.warning(f"Error en re-ranking: {e}. Usando RRF scores.")
            return chunks[:top_k]

    @staticmethod
    def _get_allowed_sensitivity(level: str) -> list[str]:
        """Devuelve los niveles de sensibilidad accesibles."""
        hierarchy = ["public", "internal", "restricted", "confidential"]
        try:
            idx = hierarchy.index(level)
            return hierarchy[:idx + 1]
        except ValueError:
            return ["public"]
