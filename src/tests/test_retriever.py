"""
Tests del HybridRetriever — RRF fusion, filtro de sensibilidad, clasificacion.
Todos los tests son unitarios puros (sin conexion a base de datos).
Ejecutar: pytest src/tests/test_retriever.py -v
"""
import pytest
from unittest.mock import MagicMock, patch

from src.rag.retriever import HybridRetriever


@pytest.fixture
def retriever():
    """HybridRetriever con dependencias externas mockeadas."""
    with patch("src.rag.retriever.get_settings"), \
         patch("src.rag.retriever.EmbeddingService"):
        return HybridRetriever(db_pool=MagicMock())


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────

class TestRRFFusion:

    def test_both_empty_returns_empty(self, retriever):
        result = retriever._reciprocal_rank_fusion([], [])
        assert result == []

    def test_only_semantic_results(self, retriever):
        semantic = [("chunk_a", 0.9), ("chunk_b", 0.7)]
        result = retriever._reciprocal_rank_fusion(semantic, [])
        ids = [r[0] for r in result]
        assert "chunk_a" in ids
        assert "chunk_b" in ids

    def test_only_lexical_results(self, retriever):
        lexical = [("chunk_x", 0.8), ("chunk_y", 0.6)]
        result = retriever._reciprocal_rank_fusion([], lexical)
        ids = [r[0] for r in result]
        assert "chunk_x" in ids
        assert "chunk_y" in ids

    def test_shared_chunk_gets_higher_score(self, retriever):
        """Un chunk que aparece en ambas listas debe tener puntuacion mayor
        que uno que solo aparece en una."""
        semantic = [("shared", 0.9), ("only_sem", 0.7)]
        lexical = [("shared", 0.8), ("only_lex", 0.6)]
        result = retriever._reciprocal_rank_fusion(semantic, lexical)

        scores = dict(result)
        assert scores["shared"] > scores["only_sem"]
        assert scores["shared"] > scores["only_lex"]

    def test_result_is_sorted_descending(self, retriever):
        semantic = [("a", 0.9), ("b", 0.7), ("c", 0.5)]
        lexical = [("b", 0.8), ("a", 0.6), ("d", 0.4)]
        result = retriever._reciprocal_rank_fusion(semantic, lexical)
        scores = [score for _, score in result]
        assert scores == sorted(scores, reverse=True)

    def test_first_ranked_chunk_has_highest_score(self, retriever):
        """El chunk en posicion 1 en ambas listas debe salir primero."""
        # "top" aparece primero en ambas → maximo score posible
        semantic = [("top", 0.99), ("mid", 0.7), ("low", 0.5)]
        lexical = [("top", 0.95), ("mid", 0.6), ("low", 0.4)]
        result = retriever._reciprocal_rank_fusion(semantic, lexical)
        assert result[0][0] == "top"

    def test_rrf_score_formula(self, retriever):
        """Verificar la formula: 1/(k + rank + 1) con k=60."""
        k = HybridRetriever.RRF_K  # 60
        semantic = [("only_chunk", 0.9)]
        lexical = []
        result = retriever._reciprocal_rank_fusion(semantic, lexical)

        expected_score = 1.0 / (k + 0 + 1)  # rank 0 → 1/61
        assert abs(result[0][1] - expected_score) < 1e-9

    def test_combining_five_chunks(self, retriever):
        semantic = [(f"s{i}", 0.9 - i * 0.1) for i in range(5)]
        lexical = [(f"l{i}", 0.8 - i * 0.1) for i in range(5)]
        result = retriever._reciprocal_rank_fusion(semantic, lexical)
        assert len(result) == 10  # 5 + 5 distintos

    def test_duplicate_chunk_ids_merged(self, retriever):
        """Si el mismo chunk_id aparece en ambas listas, debe aparecer una sola vez."""
        semantic = [("chunk_a", 0.9)]
        lexical = [("chunk_a", 0.8)]
        result = retriever._reciprocal_rank_fusion(semantic, lexical)
        assert len(result) == 1
        assert result[0][0] == "chunk_a"


# ── Filtro de sensibilidad ─────────────────────────────────────────────────────

class TestSensitivityFilter:

    def test_public_includes_only_public(self):
        result = HybridRetriever._get_allowed_sensitivity("public")
        assert result == ["public"]

    def test_internal_includes_public_and_internal(self):
        result = HybridRetriever._get_allowed_sensitivity("internal")
        assert "public" in result
        assert "internal" in result
        assert "restricted" not in result
        assert "confidential" not in result

    def test_restricted_includes_public_internal_restricted(self):
        result = HybridRetriever._get_allowed_sensitivity("restricted")
        assert "public" in result
        assert "internal" in result
        assert "restricted" in result
        assert "confidential" not in result

    def test_confidential_includes_all_levels(self):
        result = HybridRetriever._get_allowed_sensitivity("confidential")
        assert set(result) == {"public", "internal", "restricted", "confidential"}

    def test_unknown_level_defaults_to_public_only(self):
        result = HybridRetriever._get_allowed_sensitivity("super_secret")
        assert result == ["public"]

    def test_empty_string_defaults_to_public(self):
        result = HybridRetriever._get_allowed_sensitivity("")
        assert result == ["public"]

    def test_hierarchy_is_inclusive(self):
        """Cada nivel superior incluye todos los niveles inferiores."""
        public = set(HybridRetriever._get_allowed_sensitivity("public"))
        internal = set(HybridRetriever._get_allowed_sensitivity("internal"))
        restricted = set(HybridRetriever._get_allowed_sensitivity("restricted"))
        confidential = set(HybridRetriever._get_allowed_sensitivity("confidential"))

        assert public.issubset(internal)
        assert internal.issubset(restricted)
        assert restricted.issubset(confidential)


# ── Configuracion del retriever ───────────────────────────────────────────────

class TestRetrieverConfig:

    def test_rrf_k_constant(self):
        assert HybridRetriever.RRF_K == 60

    def test_no_reranker_by_default(self, retriever):
        assert retriever._use_reranker is False
        assert retriever._reranker is None
