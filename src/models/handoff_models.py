"""Modelos para el motor de derivación a agente humano."""
from enum import Enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class HandoffPriority(str, Enum):
    IMMEDIATE = "inmediata"   # agente pide explícitamente, accidente
    HIGH = "alta"             # reclamación, frustración, legal
    MEDIUM = "media"          # sin evidencia, GDPR, comercial
    LOW = "baja"              # informativa derivada


class HandoffQueue(str, Enum):
    GENERAL = "atencion_general"
    TECHNICAL = "soporte_tecnico"
    COMMERCIAL = "comercial"
    COMPLAINTS = "reclamaciones"
    AFTER_SALES = "posventa"
    LOGISTICS = "logistica"
    DPO = "dpo"
    KEY_ACCOUNTS = "key_accounts"


class HandoffReason(str, Enum):
    NO_EVIDENCE = "sin_evidencia_rag"
    LOW_CONFIDENCE = "baja_confianza"
    FORMAL_COMPLAINT = "reclamacion_formal"
    LEGAL_TOPIC = "consulta_legal"
    EXPLICIT_REQUEST = "solicitud_explicita_agente"
    FRUSTRATED_CLIENT = "cliente_frustrado"
    GDPR_REQUEST = "solicitud_gdpr"
    SENSITIVE_TOPIC = "tema_sensible"
    MAX_TURNS = "maximo_turnos_sin_resolucion"
    ASR_FAILURE = "fallo_reconocimiento_voz"
    PRICE_NOT_IN_KB = "precio_no_en_kb"
    CANCELLATION = "baja_cancelacion"
    TECHNICAL_ADVANCED = "soporte_tecnico_avanzado"


class ClientContext(BaseModel):
    caller_hash: str
    language: str = "es"
    name_if_provided: Optional[str] = None
    order_number_if_provided: Optional[str] = None
    contact_number_provided: bool = False


class HandoffSummary(BaseModel):
    handoff_id: str
    session_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    call_duration_seconds: float
    handoff_reason: HandoffReason
    priority: HandoffPriority
    routing_queue: HandoffQueue
    client_context: ClientContext

    # Resumen conversacional
    main_intent: str
    key_facts: list[str] = Field(default_factory=list)
    client_emotional_state: str = "neutro"   # neutro | frustrado | enfadado | satisfecho
    attempts_by_assistant: int = 0
    unresolved_questions: list[str] = Field(default_factory=list)

    # Para el agente
    agent_recommendations: list[str] = Field(default_factory=list)
    rag_topics_covered: list[str] = Field(default_factory=list)

    # Texto legible para pantalla de agente
    agent_display_text: str = ""

    def to_agent_display(self) -> str:
        """Genera el texto que verá el agente en su pantalla."""
        lines = [
            f"── TRANSFERENCIA SAXUN IA ── {self.timestamp.strftime('%H:%M')}",
            f"MOTIVO: {self.handoff_reason.value.replace('_', ' ').upper()}",
            f"PRIORIDAD: {self.priority.value.upper()}",
            "",
            f"RESUMEN: {self.main_intent}",
            "",
        ]
        if self.key_facts:
            lines.append("DATOS CLAVE:")
            for fact in self.key_facts:
                lines.append(f"  • {fact}")
            lines.append("")
        if self.client_emotional_state != "neutro":
            lines.append(f"ESTADO CLIENTE: {self.client_emotional_state.upper()}")
        if self.agent_recommendations:
            lines.append("ACCIÓN RECOMENDADA:")
            for i, rec in enumerate(self.agent_recommendations, 1):
                lines.append(f"  {i}. {rec}")
        return "\n".join(lines)
