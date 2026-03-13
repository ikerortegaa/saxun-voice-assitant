"""
Generador de Handoff Summary.
Crea el resumen automático que verá el agente al recibir la llamada.
Usa gpt-4o-mini para sintetizar la conversación.
"""
import uuid
from datetime import datetime

from openai import AsyncOpenAI
from loguru import logger

from src.config import get_settings
from src.models.session import Session
from src.models.handoff_models import (
    HandoffSummary, HandoffPriority, HandoffQueue,
    HandoffReason, ClientContext,
)


PRIORITY_MAP: dict[str, HandoffPriority] = {
    "reclamacion_formal":           HandoffPriority.HIGH,
    "cliente_frustrado":            HandoffPriority.HIGH,
    "consulta_legal":               HandoffPriority.HIGH,
    "solicitud_agente":             HandoffPriority.IMMEDIATE,
    "sin_evidencia_rag":            HandoffPriority.MEDIUM,
    "baja_confianza":               HandoffPriority.MEDIUM,
    "solicitud_cancelacion":        HandoffPriority.MEDIUM,
    "precio_no_en_kb":              HandoffPriority.MEDIUM,
    "solicitud_gdpr":               HandoffPriority.MEDIUM,
    "soporte_tecnico_avanzado":     HandoffPriority.MEDIUM,
    "maximo_turnos_sin_resolucion": HandoffPriority.MEDIUM,
    "fallo_reconocimiento_voz":     HandoffPriority.LOW,
    "error_tecnico":                HandoffPriority.LOW,
    "modo_emergencia":              HandoffPriority.LOW,
}

QUEUE_MAP: dict[str, HandoffQueue] = {
    "reclamacion_formal":           HandoffQueue.COMPLAINTS,
    "cliente_frustrado":            HandoffQueue.COMPLAINTS,
    "consulta_legal":               HandoffQueue.COMPLAINTS,
    "solicitud_cancelacion":        HandoffQueue.COMMERCIAL,
    "precio_no_en_kb":              HandoffQueue.COMMERCIAL,
    "soporte_tecnico_avanzado":     HandoffQueue.TECHNICAL,
    "solicitud_gdpr":               HandoffQueue.DPO,
}

EMOTIONAL_KEYWORDS = {
    "frustrado": ["enfadado", "molesto", "harto", "indignado", "furioso",
                  "no me ayuda", "no funciona", "lleváis semanas", "ya he llamado"],
    "satisfecho": ["gracias", "muy bien", "perfecto", "genial", "estupendo"],
    "neutro": [],
}


class HandoffSummaryGenerator:
    """
    Genera el handoff summary con gpt-4o-mini.
    El summary incluye: intención principal, hechos clave, recomendaciones para el agente.
    """

    SUMMARY_PROMPT = """Eres un asistente que resume conversaciones de atención al cliente.
Analiza la conversación y genera un resumen JSON para el agente humano que recibirá la llamada.

REGLAS:
- Sé conciso y útil para el agente
- Incluye solo hechos verificados de la conversación
- NO incluyas datos personales identificables (teléfonos, DNI, etc.)
- El resumen debe ayudar al agente a resolver sin repetir preguntas

FORMATO JSON:
{
  "main_intent": "descripción breve de la consulta principal",
  "key_facts": ["hecho 1", "hecho 2", "hecho 3"],
  "client_emotional_state": "neutro|frustrado|satisfecho",
  "unresolved_questions": ["pregunta no resuelta 1"],
  "agent_recommendations": ["recomendación 1", "recomendación 2"],
  "rag_topics_covered": ["tema 1", "tema 2"]
}"""

    def __init__(self):
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_llm_model

    async def generate(
        self,
        session: Session,
        handoff_reason: str,
        call_duration_seconds: float,
    ) -> HandoffSummary:
        """Genera el HandoffSummary completo para una sesión."""
        # Determinar prioridad y cola
        try:
            reason_enum = HandoffReason(handoff_reason)
        except ValueError:
            reason_enum = HandoffReason.NO_EVIDENCE

        priority = PRIORITY_MAP.get(handoff_reason, HandoffPriority.MEDIUM)
        queue = QUEUE_MAP.get(handoff_reason, HandoffQueue.GENERAL)

        # Detectar estado emocional del historial
        emotional_state = self._detect_emotional_state(session)

        # Generar summary con LLM
        llm_data = await self._llm_summarize(session)

        # Construir contexto del cliente (sin PII real)
        client_ctx = ClientContext(
            caller_hash=session.caller_hash,
            language=session.language,
            name_if_provided=self._extract_name(session),
            order_number_if_provided=self._extract_order_number(session),
            contact_number_provided=False,  # No almacenamos números
        )

        summary = HandoffSummary(
            handoff_id=f"hoff_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            session_id=session.session_id,
            call_duration_seconds=call_duration_seconds,
            handoff_reason=reason_enum,
            priority=priority,
            routing_queue=queue,
            client_context=client_ctx,
            main_intent=llm_data.get("main_intent", "Consulta no especificada"),
            key_facts=llm_data.get("key_facts", []),
            client_emotional_state=emotional_state,
            attempts_by_assistant=session.turn_count // 2,
            unresolved_questions=llm_data.get("unresolved_questions", []),
            agent_recommendations=llm_data.get("agent_recommendations", []),
            rag_topics_covered=llm_data.get("rag_topics_covered", []),
        )
        summary.agent_display_text = summary.to_agent_display()
        return summary

    async def _llm_summarize(self, session: Session) -> dict:
        """Llama a gpt-4o-mini para sintetizar la conversación."""
        if not session.turns:
            return {"main_intent": "Llamada sin contenido", "key_facts": []}

        conversation_text = "\n".join(
            f"{'CLIENTE' if t.role == 'user' else 'ASISTENTE'}: "
            f"{t.content_redacted or t.content}"
            for t in session.turns
        )

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": self.SUMMARY_PROMPT},
                    {"role": "user", "content": f"CONVERSACIÓN:\n{conversation_text}"},
                ],
                temperature=0.1,
                max_tokens=400,
                response_format={"type": "json_object"},
                timeout=6.0,
            )
            import json
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.warning(f"Error en LLM summary: {e}")
            return {
                "main_intent": "Error al generar resumen automático",
                "key_facts": [f"Turnos de conversación: {session.turn_count}"],
                "agent_recommendations": ["Revisar grabación si disponible"],
            }

    def _detect_emotional_state(self, session: Session) -> str:
        """Detecta estado emocional del cliente basado en sus mensajes."""
        user_texts = " ".join(
            t.content.lower()
            for t in session.turns
            if t.role == "user"
        )
        for state, keywords in EMOTIONAL_KEYWORDS.items():
            if keywords and any(kw in user_texts for kw in keywords):
                return state
        return "neutro"

    @staticmethod
    def _extract_name(session: Session) -> None:
        """Intenta extraer el nombre del cliente del historial (sin PII)."""
        # En MVP no almacenamos nombres. Retornar None para GDPR-compliance.
        return None

    @staticmethod
    def _extract_order_number(session: Session) -> None:
        """Extrae número de pedido si fue mencionado."""
        import re
        for turn in session.turns:
            if turn.role == "user":
                # Buscar patrón de número de pedido (ej: 8734, #1234)
                m = re.search(r'(?:pedido|orden|referencia)[^\d]*(\d{4,10})', turn.content, re.IGNORECASE)
                if m:
                    return m.group(1)
        return None
