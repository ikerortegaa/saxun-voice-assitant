"""
Tests del orquestador de conversacion — state machine, deteccion de idioma,
modelo de sesion y guards del pipeline de voz.
Ejecutar: pytest src/tests/test_conversation.py -v
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.conversation.state_machine import ConversationOrchestrator
from src.models.session import Session, ConversationState
from src.voice.stt import STTResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session(lang: str = "es") -> Session:
    return Session(
        session_id="test-session",
        call_sid="CA001",
        caller_hash="hash001",
        language=lang,
        state=ConversationState.INTENT_CAPTURE,
    )


def _stt(text: str = "Hola", confidence: float = 0.95, is_final: bool = True) -> STTResult:
    return STTResult(text=text, confidence=confidence, is_final=is_final, language="es")


@pytest.fixture
def orchestrator():
    """Instancia del orquestador con todas las dependencias mockeadas."""
    session = _make_session()

    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=MagicMock(chunks=[], latency_ms=50, query="test"))

    mock_tts = MagicMock()
    mock_tts.synthesize = AsyncMock(return_value=b"\x00" * 8000)

    mock_ctx = MagicMock()
    mock_ctx.save_session = AsyncMock()
    mock_ctx.end_session = AsyncMock()

    mock_handoff = MagicMock()
    mock_handoff.execute_handoff = AsyncMock()
    mock_handoff.get_queue = MagicMock(return_value="general")

    mock_send_audio = AsyncMock()

    mock_settings = MagicMock()
    mock_settings.emergency_mode = False
    mock_settings.rag_top_k = 3
    mock_settings.rag_confidence_threshold = 0.65

    mock_redactor = MagicMock()
    mock_redactor.has_injection_attempt = MagicMock(return_value=False)
    mock_redactor.redact = MagicMock(side_effect=lambda x: x)

    mock_audit = MagicMock()
    for method in ("log", "log_call_start", "log_call_end", "log_rag_query",
                   "log_handoff", "log_injection_attempt"):
        setattr(mock_audit, method, AsyncMock())

    with patch("src.conversation.state_machine.get_settings", return_value=mock_settings), \
         patch("src.conversation.state_machine.RAGGuardrails") as mock_rag_cls, \
         patch("src.conversation.state_machine.get_redactor", return_value=mock_redactor), \
         patch("src.conversation.state_machine.get_audit_logger", return_value=mock_audit):

        mock_guardrails = MagicMock()
        mock_guardrails.generate_response = AsyncMock()
        mock_rag_cls.return_value = mock_guardrails

        orch = ConversationOrchestrator(
            session=session,
            retriever=mock_retriever,
            tts=mock_tts,
            context_manager=mock_ctx,
            send_audio_fn=mock_send_audio,
            handoff_engine=mock_handoff,
        )
        yield orch


# ── Session Model ─────────────────────────────────────────────────────────────

class TestSessionModel:

    @pytest.fixture
    def session(self):
        return _make_session()

    def test_add_turn_increments_count(self, session):
        assert session.turn_count == 0
        session.add_turn("user", "Hola")
        assert session.turn_count == 1
        session.add_turn("assistant", "Buenos dias")
        assert session.turn_count == 2

    def test_add_turn_appends_to_list(self, session):
        session.add_turn("user", "Quiero saber el horario")
        assert len(session.turns) == 1
        assert session.turns[0].content == "Quiero saber el horario"
        assert session.turns[0].role == "user"

    def test_add_turn_assigns_turn_number(self, session):
        session.add_turn("user", "Mensaje 1")
        session.add_turn("assistant", "Respuesta 1")
        assert session.turns[0].turn_number == 1
        assert session.turns[1].turn_number == 2

    def test_get_history_empty_session(self, session):
        assert session.get_history_for_llm() == []

    def test_get_history_uses_redacted_content(self, session):
        session.add_turn("user", "Mi DNI es 12345678A", content_redacted="Mi DNI es [REDACTED]")
        history = session.get_history_for_llm()
        assert history[0]["content"] == "Mi DNI es [REDACTED]"

    def test_get_history_falls_back_to_original(self, session):
        session.add_turn("user", "Cual es el horario")
        history = session.get_history_for_llm()
        assert history[0]["content"] == "Cual es el horario"

    def test_get_history_max_turns_limits_output(self, session):
        for i in range(20):
            session.add_turn("user" if i % 2 == 0 else "assistant", f"msg {i}")
        history = session.get_history_for_llm(max_turns=3)
        assert len(history) <= 6  # max_turns * 2 roles

    def test_get_history_maps_assistant_role(self, session):
        session.add_turn("assistant", "Buenos dias")
        history = session.get_history_for_llm()
        assert history[0]["role"] == "assistant"

    def test_get_history_maps_user_role(self, session):
        session.add_turn("user", "Hola")
        history = session.get_history_for_llm()
        assert history[0]["role"] == "user"

    def test_handoff_triggered_default_false(self, session):
        assert session.handoff_triggered is False

    def test_failed_asr_count_default_zero(self, session):
        assert session.failed_asr_count == 0

    def test_unresolved_turns_default_zero(self, session):
        assert session.unresolved_turns == 0

    def test_initial_state_is_greeting(self):
        s = Session(session_id="s1", call_sid="CA1", caller_hash="h1")
        assert s.state == ConversationState.GREETING


# ── Language Detection (metodo estatico) ──────────────────────────────────────

class TestLanguageDetection:

    def test_detects_english_in_english(self):
        assert ConversationOrchestrator._detect_language_request("in english please") == "en"

    def test_detects_speak_english(self):
        assert ConversationOrchestrator._detect_language_request("can you speak english") == "en"

    def test_detects_english_from_spanish_request(self):
        # Deepgram Nova-2 transcribe el español con tildes → inglés (con acento)
        assert ConversationOrchestrator._detect_language_request("atender en inglés") == "en"

    def test_detects_hablar_ingles(self):
        assert ConversationOrchestrator._detect_language_request("puede hablar en inglés") == "en"

    def test_detects_catalan(self):
        assert ConversationOrchestrator._detect_language_request("catalán por favor") == "ca"

    def test_detects_catalan_request(self):
        assert ConversationOrchestrator._detect_language_request("en català si us plau") == "ca"

    def test_detects_spanish(self):
        assert ConversationOrchestrator._detect_language_request("prefiero en español") == "es"

    def test_detects_castellano(self):
        assert ConversationOrchestrator._detect_language_request("en castellano por favor") == "es"

    def test_no_language_in_normal_query(self):
        assert ConversationOrchestrator._detect_language_request("Cual es vuestro horario") is None

    def test_no_language_in_complaint(self):
        assert ConversationOrchestrator._detect_language_request("Quiero poner una reclamacion") is None

    def test_no_language_in_empty_string(self):
        assert ConversationOrchestrator._detect_language_request("") is None

    def test_case_insensitive_detection(self):
        assert ConversationOrchestrator._detect_language_request("IN ENGLISH PLEASE") == "en"

    def test_no_false_positive_on_tech_query(self):
        assert ConversationOrchestrator._detect_language_request("no funciona mi dispositivo") is None


# ── on_transcript guards ───────────────────────────────────────────────────────

class TestOnTranscriptGuards:

    @pytest.mark.asyncio
    async def test_ignores_non_final_transcript(self, orchestrator):
        result = _stt(is_final=False)
        orchestrator._process_turn = AsyncMock()
        await orchestrator.on_transcript(result)
        orchestrator._process_turn.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_empty_text(self, orchestrator):
        result = _stt(text="   ", is_final=True)
        orchestrator._process_turn = AsyncMock()
        await orchestrator.on_transcript(result)
        orchestrator._process_turn.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_transcript_during_tts(self, orchestrator):
        orchestrator._tts_until = time.time() + 10.0
        result = _stt(text="Cual es el horario", is_final=True)
        orchestrator._process_turn = AsyncMock()
        await orchestrator.on_transcript(result)
        orchestrator._process_turn.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_when_already_processing(self, orchestrator):
        orchestrator._processing = True
        result = _stt(text="Cual es el horario", is_final=True)
        orchestrator._process_turn = AsyncMock()
        await orchestrator.on_transcript(result)
        orchestrator._process_turn.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_valid_transcript(self, orchestrator):
        orchestrator._tts_until = 0.0
        result = _stt(text="Cual es el horario", is_final=True)
        orchestrator._process_turn = AsyncMock()
        await orchestrator.on_transcript(result)
        orchestrator._process_turn.assert_called_once()

    @pytest.mark.asyncio
    async def test_resets_processing_flag_after_success(self, orchestrator):
        orchestrator._tts_until = 0.0
        result = _stt(text="Hola", is_final=True)
        orchestrator._process_turn = AsyncMock()
        await orchestrator.on_transcript(result)
        assert orchestrator._processing is False

    @pytest.mark.asyncio
    async def test_resets_processing_flag_after_exception(self, orchestrator):
        orchestrator._tts_until = 0.0
        result = _stt(text="Hola", is_final=True)
        orchestrator._process_turn = AsyncMock(side_effect=RuntimeError("test error"))
        orchestrator._speak_and_handoff = AsyncMock()
        await orchestrator.on_transcript(result)
        assert orchestrator._processing is False


# ── on_silence guards ─────────────────────────────────────────────────────────

class TestOnSilenceGuards:

    @pytest.mark.asyncio
    async def test_ignored_when_ended(self, orchestrator):
        orchestrator._session.state = ConversationState.ENDED
        orchestrator._speak = AsyncMock()
        await orchestrator.on_silence(10.0)
        orchestrator._speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignored_when_handoff_active(self, orchestrator):
        orchestrator._session.state = ConversationState.HANDOFF_ACTIVE
        orchestrator._speak = AsyncMock()
        await orchestrator.on_silence(10.0)
        orchestrator._speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignored_during_tts(self, orchestrator):
        orchestrator._tts_until = time.time() + 10.0
        orchestrator._speak = AsyncMock()
        await orchestrator.on_silence(5.0)
        orchestrator._speak.assert_not_called()

    @pytest.mark.asyncio
    async def test_first_timeout_sends_prompt(self, orchestrator):
        orchestrator._tts_until = 0.0
        orchestrator._speak = AsyncMock()
        orchestrator.on_call_end = AsyncMock()
        await orchestrator.on_silence(4.0)   # entre 3s y 6s
        orchestrator._speak.assert_called_once()
        orchestrator.on_call_end.assert_not_called()

    @pytest.mark.asyncio
    async def test_final_timeout_ends_call(self, orchestrator):
        orchestrator._tts_until = 0.0
        orchestrator._speak = AsyncMock()
        orchestrator.on_call_end = AsyncMock()
        await orchestrator.on_silence(7.0)   # >= 6s
        orchestrator.on_call_end.assert_called_once_with(reason="silence_timeout")

    @pytest.mark.asyncio
    async def test_first_timeout_uses_correct_language_es(self, orchestrator):
        orchestrator._tts_until = 0.0
        orchestrator._session.language = "es"
        orchestrator._speak = AsyncMock()
        orchestrator.on_call_end = AsyncMock()
        await orchestrator.on_silence(4.0)
        text = orchestrator._speak.call_args[0][0]
        assert "Sigue" in text or "sigue" in text

    @pytest.mark.asyncio
    async def test_first_timeout_uses_correct_language_en(self, orchestrator):
        orchestrator._tts_until = 0.0
        orchestrator._session.language = "en"
        orchestrator._speak = AsyncMock()
        orchestrator.on_call_end = AsyncMock()
        await orchestrator.on_silence(4.0)
        text = orchestrator._speak.call_args[0][0]
        assert "there" in text.lower()


# ── on_barge_in guards ────────────────────────────────────────────────────────

class TestOnBargeIn:

    @pytest.mark.asyncio
    async def test_single_word_ignored(self, orchestrator):
        orchestrator._process_turn = AsyncMock()
        await orchestrator.on_barge_in("si", 0.95)
        orchestrator._process_turn.assert_not_called()

    @pytest.mark.asyncio
    async def test_low_confidence_ignored(self, orchestrator):
        orchestrator._process_turn = AsyncMock()
        await orchestrator.on_barge_in("quiero hablar con alguien", 0.60)
        orchestrator._process_turn.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_barge_in_processed(self, orchestrator):
        orchestrator._process_turn = AsyncMock()
        await orchestrator.on_barge_in("espera quiero otra cosa", 0.90)
        orchestrator._process_turn.assert_called_once()

    @pytest.mark.asyncio
    async def test_barge_in_confidence_boundary(self, orchestrator):
        """Exactamente en 0.65 debe procesarse."""
        orchestrator._process_turn = AsyncMock()
        await orchestrator.on_barge_in("quiero otra informacion", 0.65)
        orchestrator._process_turn.assert_called_once()


# ── Constantes del orquestador ────────────────────────────────────────────────

class TestOrchestratorConstants:

    def test_max_asr_retries(self):
        assert ConversationOrchestrator.MAX_ASR_RETRIES == 2

    def test_max_unresolved_turns(self):
        assert ConversationOrchestrator.MAX_UNRESOLVED_TURNS == 3

    def test_max_turn_count(self):
        assert ConversationOrchestrator.MAX_TURN_COUNT == 20

    def test_silence_timeouts(self):
        assert ConversationOrchestrator.SILENCE_TIMEOUT_1 == 3.0
        assert ConversationOrchestrator.SILENCE_TIMEOUT_2 == 6.0
