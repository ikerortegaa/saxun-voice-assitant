"""
Tests del motor de handoff — mapeo de colas, prioridades, estado emocional,
extraccion de numero de pedido.
Todos los tests son unitarios puros (sin llamadas a LLM ni Twilio).
Ejecutar: pytest src/tests/test_handoff.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.handoff.summary_generator import (
    HandoffSummaryGenerator,
    QUEUE_MAP,
    PRIORITY_MAP,
    EMOTIONAL_KEYWORDS,
)
from src.models.handoff_models import HandoffQueue, HandoffPriority
from src.models.session import Session, ConversationState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_session_with_turns(messages: list[tuple[str, str]]) -> Session:
    session = Session(
        session_id="s1",
        call_sid="CA001",
        caller_hash="h1",
        language="es",
    )
    for role, content in messages:
        session.add_turn(role, content)
    return session


@pytest.fixture
def summary_gen():
    with patch("src.handoff.summary_generator.get_settings") as mock_settings, \
         patch("src.handoff.summary_generator.AsyncOpenAI"):
        mock_settings.return_value.openai_api_key = "test"
        mock_settings.return_value.openai_llm_model = "gpt-4o-mini"
        return HandoffSummaryGenerator()


# ── Mapeo de colas (QUEUE_MAP) ─────────────────────────────────────────────────

class TestQueueMapping:

    def test_reclamacion_formal_goes_to_complaints(self):
        assert QUEUE_MAP.get("reclamacion_formal") == HandoffQueue.COMPLAINTS

    def test_cliente_frustrado_goes_to_complaints(self):
        assert QUEUE_MAP.get("cliente_frustrado") == HandoffQueue.COMPLAINTS

    def test_consulta_legal_goes_to_complaints(self):
        assert QUEUE_MAP.get("consulta_legal") == HandoffQueue.COMPLAINTS

    def test_solicitud_cancelacion_goes_to_commercial(self):
        assert QUEUE_MAP.get("solicitud_cancelacion") == HandoffQueue.COMMERCIAL

    def test_precio_no_en_kb_goes_to_commercial(self):
        assert QUEUE_MAP.get("precio_no_en_kb") == HandoffQueue.COMMERCIAL

    def test_soporte_tecnico_avanzado_goes_to_technical(self):
        assert QUEUE_MAP.get("soporte_tecnico_avanzado") == HandoffQueue.TECHNICAL

    def test_solicitud_gdpr_goes_to_dpo(self):
        assert QUEUE_MAP.get("solicitud_gdpr") == HandoffQueue.DPO

    def test_unknown_reason_returns_none(self):
        """Razones desconocidas no estan en el mapa → get() devuelve None."""
        assert QUEUE_MAP.get("motivo_desconocido") is None

    def test_handoff_engine_get_queue_unknown_defaults_to_general(self):
        """HandoffEngine.get_queue() debe devolver GENERAL para razones desconocidas."""
        with patch("src.handoff.engine.get_settings"), \
             patch("src.handoff.engine.TwilioClient"), \
             patch("src.handoff.engine.HandoffSummaryGenerator"):
            from src.handoff.engine import HandoffEngine
            engine = HandoffEngine()
            result = engine.get_queue("motivo_totalmente_desconocido")
            assert result == HandoffQueue.GENERAL.value


# ── Mapeo de prioridades (PRIORITY_MAP) ───────────────────────────────────────

class TestPriorityMapping:

    def test_reclamacion_formal_is_high_priority(self):
        assert PRIORITY_MAP.get("reclamacion_formal") == HandoffPriority.HIGH

    def test_cliente_frustrado_is_high_priority(self):
        assert PRIORITY_MAP.get("cliente_frustrado") == HandoffPriority.HIGH

    def test_consulta_legal_is_high_priority(self):
        assert PRIORITY_MAP.get("consulta_legal") == HandoffPriority.HIGH

    def test_solicitud_agente_is_immediate(self):
        assert PRIORITY_MAP.get("solicitud_agente") == HandoffPriority.IMMEDIATE

    def test_sin_evidencia_rag_is_medium(self):
        assert PRIORITY_MAP.get("sin_evidencia_rag") == HandoffPriority.MEDIUM

    def test_baja_confianza_is_medium(self):
        assert PRIORITY_MAP.get("baja_confianza") == HandoffPriority.MEDIUM

    def test_solicitud_cancelacion_is_medium(self):
        assert PRIORITY_MAP.get("solicitud_cancelacion") == HandoffPriority.MEDIUM

    def test_error_tecnico_is_low(self):
        assert PRIORITY_MAP.get("error_tecnico") == HandoffPriority.LOW

    def test_fallo_reconocimiento_voz_is_low(self):
        assert PRIORITY_MAP.get("fallo_reconocimiento_voz") == HandoffPriority.LOW

    def test_maximo_turnos_is_medium(self):
        assert PRIORITY_MAP.get("maximo_turnos_sin_resolucion") == HandoffPriority.MEDIUM


# ── Deteccion de estado emocional ─────────────────────────────────────────────

class TestEmotionalStateDetection:

    def test_detects_frustrated_enfadado(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "Estoy muy enfadado, llevan semanas sin ayudarme"),
        ])
        state = summary_gen._detect_emotional_state(session)
        assert state == "frustrado"

    def test_detects_frustrated_molesto(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "Estoy muy molesto con este servicio"),
        ])
        state = summary_gen._detect_emotional_state(session)
        assert state == "frustrado"

    def test_detects_frustrated_harto(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "Estoy harto de esperar, ya he llamado varias veces"),
        ])
        state = summary_gen._detect_emotional_state(session)
        assert state == "frustrado"

    def test_detects_frustrated_ya_he_llamado(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "ya he llamado tres veces y nadie me soluciona nada"),
        ])
        state = summary_gen._detect_emotional_state(session)
        assert state == "frustrado"

    def test_detects_satisfied_gracias(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "Muchas gracias, ha sido de gran ayuda"),
        ])
        state = summary_gen._detect_emotional_state(session)
        assert state == "satisfecho"

    def test_detects_satisfied_perfecto(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "perfecto, exactamente lo que necesitaba"),
        ])
        state = summary_gen._detect_emotional_state(session)
        assert state == "satisfecho"

    def test_neutral_for_normal_query(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "Quiero saber el horario de atencion"),
            ("assistant", "Atendemos de lunes a viernes de nueve a seis"),
        ])
        state = summary_gen._detect_emotional_state(session)
        assert state == "neutro"

    def test_neutral_for_empty_session(self, summary_gen):
        session = _make_session_with_turns([])
        state = summary_gen._detect_emotional_state(session)
        assert state == "neutro"

    def test_only_user_turns_are_analyzed(self, summary_gen):
        """Los mensajes del asistente no deben influir en la deteccion emocional."""
        session = _make_session_with_turns([
            ("assistant", "Le entiendo, estoy aqui para ayudarle"),
            ("user", "Quiero informacion sobre la garantia"),
        ])
        state = summary_gen._detect_emotional_state(session)
        assert state == "neutro"


# ── Extraccion de numero de pedido ────────────────────────────────────────────

class TestOrderNumberExtraction:

    def test_extracts_pedido_number(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "Mi pedido numero 8734 no ha llegado"),
        ])
        result = summary_gen._extract_order_number(session)
        assert result == "8734"

    def test_extracts_referencia_number(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "La referencia es 12345"),
        ])
        result = summary_gen._extract_order_number(session)
        assert result == "12345"

    def test_extracts_orden_number(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "Mi orden 99001 sigue pendiente"),
        ])
        result = summary_gen._extract_order_number(session)
        assert result == "99001"

    def test_no_number_returns_none(self, summary_gen):
        session = _make_session_with_turns([
            ("user", "Quiero saber el horario de atencion"),
        ])
        result = summary_gen._extract_order_number(session)
        assert result is None

    def test_empty_session_returns_none(self, summary_gen):
        session = _make_session_with_turns([])
        result = summary_gen._extract_order_number(session)
        assert result is None

    def test_short_number_not_extracted(self, summary_gen):
        """Numeros de menos de 4 digitos no deben extraerse como numero de pedido."""
        session = _make_session_with_turns([
            ("user", "pedido 123"),  # solo 3 digitos
        ])
        result = summary_gen._extract_order_number(session)
        assert result is None

    def test_extracts_first_match(self, summary_gen):
        """Si hay varios pedidos mencionados, extrae el primero."""
        session = _make_session_with_turns([
            ("user", "El pedido 1111 y el pedido 2222 tienen problema"),
        ])
        result = summary_gen._extract_order_number(session)
        assert result == "1111"


# ── Integridad del mapa de colas ──────────────────────────────────────────────

class TestHandoffModels:

    def test_all_priority_map_values_are_handoff_priority(self):
        for key, value in PRIORITY_MAP.items():
            assert isinstance(value, HandoffPriority), \
                f"PRIORITY_MAP['{key}'] no es HandoffPriority: {value}"

    def test_all_queue_map_values_are_handoff_queue(self):
        for key, value in QUEUE_MAP.items():
            assert isinstance(value, HandoffQueue), \
                f"QUEUE_MAP['{key}'] no es HandoffQueue: {value}"

    def test_high_priority_reasons_route_to_complaints(self):
        """Las razones de alta prioridad deben ir a Complaints o ser inmediatas."""
        high_priority_reasons = [
            key for key, prio in PRIORITY_MAP.items()
            if prio in (HandoffPriority.HIGH, HandoffPriority.IMMEDIATE)
        ]
        # Todas las razones de alta prioridad en QUEUE_MAP deben ir a COMPLAINTS
        for reason in high_priority_reasons:
            if reason in QUEUE_MAP:
                assert QUEUE_MAP[reason] == HandoffQueue.COMPLAINTS, \
                    f"Razon de alta prioridad '{reason}' no va a COMPLAINTS"
