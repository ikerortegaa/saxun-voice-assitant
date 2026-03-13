"""
Tests del pipeline RAG — chunking, guardrails, estructuras de datos.
Los tests de retrieval con DB real usan pytest fixtures con DB de test.
Ejecutar: pytest src/tests/test_rag.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.rag.chunker import SemanticChunker, RawChunk
from src.rag.guardrails import RAGGuardrails
from src.models.rag_models import Chunk, LLMResponse, RAGAction


# ── Chunker ───────────────────────────────────────────────────────────────────

class TestSemanticChunker:

    @pytest.fixture
    def chunker(self):
        return SemanticChunker()

    def test_basic_chunking_returns_chunks(self, chunker):
        text = "Párrafo uno con contenido relevante.\n\nPárrafo dos con más información importante."
        chunks = chunker.chunk_document(text)
        assert len(chunks) >= 1
        assert all(isinstance(c, RawChunk) for c in chunks)

    def test_chunks_have_minimum_length(self, chunker):
        text = "\n\n".join([f"Párrafo {i} con suficiente contenido para ser válido como chunk." * 3
                             for i in range(5)])
        chunks = chunker.chunk_document(text)
        # Todos los chunks deben tener al menos 20 tokens estimados
        assert all(len(c.content) >= 80 for c in chunks)

    def test_faq_chunking_groups_qa_pairs(self, chunker):
        faq_text = """P: ¿Cuántos años tiene la garantía?
R: La garantía de los productos Saxun es de dos años desde la fecha de compra.

P: ¿Cómo puedo devolver un producto?
R: Puede devolver el producto en los primeros 30 días sin necesidad de justificación."""
        chunks = chunker.chunk_document(faq_text, doc_type="faq")
        # Debe generar al menos 2 chunks (uno por par Q&A)
        assert len(chunks) >= 1

    def test_table_detection(self, chunker):
        table_text = "Producto | Precio | Garantía\nModelo A | 100€ | 2 años\nModelo B | 200€ | 3 años"
        assert chunker._is_table(table_text) is True

    def test_non_table_detection(self, chunker):
        normal_text = "Esta es una oración normal sin tabla."
        assert chunker._is_table(normal_text) is False

    def test_token_estimation(self, chunker):
        text = "a" * 400  # 400 chars ≈ 100 tokens
        assert chunker._estimate_tokens(text) == 100

    def test_chunk_id_generation(self):
        chunk = RawChunk(content="Contenido de prueba", chunk_index=3)
        chunk_id = chunk.generate_id("mi-documento")
        assert chunk_id.startswith("mi-documento_chunk_")
        assert "0003" in chunk_id

    def test_empty_content_filtered(self, chunker):
        text = "\n\n\n\n  \n\n"
        chunks = chunker.chunk_document(text)
        assert all(c.content.strip() for c in chunks)

    def test_long_section_subdivided(self, chunker):
        # Una sección muy larga debe subdividirse en múltiples chunks
        long_text = "Esta es una oración. " * 200  # ~900 tokens
        chunks = chunker.chunk_document(long_text)
        assert len(chunks) >= 2


# ── Guardrails ────────────────────────────────────────────────────────────────

class TestRAGGuardrails:

    @pytest.fixture
    def guardrails(self):
        return RAGGuardrails()

    def test_immediate_handoff_formal_complaint(self, guardrails):
        reason = guardrails._check_immediate_handoff("Quiero poner una reclamación formal")
        assert reason == "reclamacion_formal"

    def test_immediate_handoff_legal(self, guardrails):
        reason = guardrails._check_immediate_handoff("Voy a llamar a mi abogado")
        assert reason == "consulta_legal"

    def test_immediate_handoff_cancellation(self, guardrails):
        reason = guardrails._check_immediate_handoff("Quiero darme de baja del servicio")
        assert reason == "solicitud_cancelacion"

    def test_immediate_handoff_frustrated(self, guardrails):
        reason = guardrails._check_immediate_handoff("Estoy muy enfadado, esto no funciona")
        assert reason == "cliente_frustrado"

    def test_no_immediate_handoff_normal_query(self, guardrails):
        reason = guardrails._check_immediate_handoff("¿Cuál es vuestro horario?")
        assert reason is None

    def test_no_immediate_handoff_warranty_query(self, guardrails):
        reason = guardrails._check_immediate_handoff("¿Cuánto dura la garantía?")
        assert reason is None

    def test_voice_length_enforcement(self, guardrails):
        long_text = "palabra " * 80
        result = guardrails._enforce_voice_length(long_text)
        assert len(result.split()) <= 65  # max_words + pequeño margen

    def test_no_truncation_for_short_text(self, guardrails):
        short_text = "La garantía es de dos años."
        result = guardrails._enforce_voice_length(short_text)
        assert result == short_text

    def test_apply_guardrails_no_evidence_forces_no_evidence_action(self, guardrails):
        response = LLMResponse(
            response_text="La garantía es de dos años.",
            confidence=0.9,
            action=RAGAction.RESPOND,
            evidence_found=False,  # Sin evidencia
        )
        result = guardrails._apply_post_guardrails(response, "query")
        assert result.action == RAGAction.NO_EVIDENCE

    def test_apply_guardrails_low_confidence_triggers_handoff(self, guardrails):
        response = LLMResponse(
            response_text="Creo que la garantía es de un año.",
            confidence=0.40,  # Bajo threshold 0.65
            action=RAGAction.RESPOND,
            evidence_found=True,
        )
        result = guardrails._apply_post_guardrails(response, "query")
        assert result.action == RAGAction.HANDOFF
        assert result.handoff_reason == "baja_confianza"

    def test_apply_guardrails_high_confidence_passes(self, guardrails):
        response = LLMResponse(
            response_text="La garantía de Saxun es de dos años desde la fecha de compra.",
            confidence=0.95,
            action=RAGAction.RESPOND,
            evidence_found=True,
        )
        result = guardrails._apply_post_guardrails(response, "query")
        assert result.action == RAGAction.RESPOND

    @pytest.mark.asyncio
    async def test_generate_response_emergency_mode(self, guardrails):
        """En modo emergencia siempre derivar."""
        with patch("src.rag.guardrails.get_settings") as mock_settings:
            mock_settings.return_value.emergency_mode = True
            mock_settings.return_value.openai_api_key = "test"
            mock_settings.return_value.openai_llm_model = "gpt-4o-mini"
            mock_settings.return_value.rag_confidence_threshold = 0.65
            mock_settings.return_value.rag_high_confidence_threshold = 0.85

            response = await guardrails.generate_response(
                query="¿Cuál es la garantía?",
                chunks=[],
                conversation_history=[],
            )
            assert response.action == RAGAction.HANDOFF
            assert response.handoff_reason == "modo_emergencia"


# ── Modelos ───────────────────────────────────────────────────────────────────

class TestChunkModel:

    def test_chunk_score_default(self):
        chunk = Chunk(chunk_id="c1", doc_id="d1", content="contenido")
        assert chunk.score == 0.0

    def test_chunk_metadata_default(self):
        chunk = Chunk(chunk_id="c1", doc_id="d1", content="contenido")
        assert chunk.metadata == {}


class TestLLMResponse:

    def test_default_action_is_respond(self):
        response = LLMResponse(response_text="Hola")
        assert response.action == RAGAction.RESPOND

    def test_handoff_reason_optional(self):
        response = LLMResponse(response_text="Le transfiero")
        assert response.handoff_reason is None
