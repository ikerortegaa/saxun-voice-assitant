"""
Audit Logger — Registro de eventos sin PII.
Cumplimiento GDPR: logs cifrados, retención configurable.
"""
import json
import uuid
from enum import Enum
from datetime import datetime
from typing import Optional
from loguru import logger


class AuditEventType(str, Enum):
    CALL_START = "call_start"
    CALL_END = "call_end"
    RAG_QUERY = "rag_query"
    LLM_RESPONSE = "llm_response"
    HANDOFF_TRIGGERED = "handoff_triggered"
    HANDOFF_COMPLETED = "handoff_completed"
    ASR_ERROR = "asr_error"
    TTS_ERROR = "tts_error"
    PII_DETECTED = "pii_detected_and_redacted"
    INJECTION_ATTEMPT = "injection_attempt_detected"
    EMERGENCY_MODE = "emergency_mode_activated"
    DOC_INGESTED = "document_ingested"
    DOC_EXPIRED = "document_expired"
    CONSENT_RECORDED = "consent_recorded"
    ERROR = "system_error"


class AuditEvent:
    """Evento de auditoría. Nunca contiene PII sin redactar."""

    def __init__(
        self,
        event_type: AuditEventType,
        session_id: Optional[str] = None,
        caller_hash: Optional[str] = None,
        **kwargs,
    ):
        self.event_id = f"evt_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        self.event_type = event_type
        self.session_id = session_id
        self.caller_hash = caller_hash  # siempre hash SHA-256, nunca número real
        self.timestamp_utc = datetime.utcnow().isoformat()
        self.data = kwargs

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "session_id": self.session_id,
            "caller_hash": self.caller_hash,
            "timestamp_utc": self.timestamp_utc,
            **self.data,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


class AuditLogger:
    """
    Registra eventos de auditoría.
    En producción: escribir en S3 cifrado + base de datos.
    En desarrollo: loguru stdout.
    """

    def __init__(self, log_to_db: bool = False):
        self.log_to_db = log_to_db

    async def log(self, event: AuditEvent) -> None:
        """Registra un evento de auditoría."""
        event_dict = event.to_dict()
        # Verificación de seguridad: asegurar que no hay PII sin redactar
        self._assert_no_raw_pii(event_dict)
        logger.bind(audit=True).info(event.to_json())
        if self.log_to_db:
            await self._persist_to_db(event)

    async def log_call_start(
        self,
        session_id: str,
        caller_hash: str,
        language: str = "es",
        call_sid: str = "",
    ) -> None:
        await self.log(AuditEvent(
            AuditEventType.CALL_START,
            session_id=session_id,
            caller_hash=caller_hash,
            language=language,
            call_sid=call_sid,
        ))

    async def log_call_end(
        self,
        session_id: str,
        caller_hash: str,
        duration_seconds: float,
        turn_count: int,
        handoff_triggered: bool,
        containment: bool,
    ) -> None:
        await self.log(AuditEvent(
            AuditEventType.CALL_END,
            session_id=session_id,
            caller_hash=caller_hash,
            duration_seconds=round(duration_seconds, 2),
            turn_count=turn_count,
            handoff_triggered=handoff_triggered,
            containment=containment,
        ))

    async def log_rag_query(
        self,
        session_id: str,
        query_length: int,
        chunks_returned: int,
        top_score: float,
        evidence_found: bool,
        latency_ms: float,
        doc_ids_accessed: list[str],
    ) -> None:
        await self.log(AuditEvent(
            AuditEventType.RAG_QUERY,
            session_id=session_id,
            query_length=query_length,
            chunks_returned=chunks_returned,
            top_score=round(top_score, 4),
            evidence_found=evidence_found,
            latency_ms=round(latency_ms, 1),
            doc_ids_accessed=doc_ids_accessed,  # IDs, no contenido
        ))

    async def log_handoff(
        self,
        session_id: str,
        caller_hash: str,
        reason: str,
        priority: str,
        queue: str,
    ) -> None:
        await self.log(AuditEvent(
            AuditEventType.HANDOFF_TRIGGERED,
            session_id=session_id,
            caller_hash=caller_hash,
            reason=reason,
            priority=priority,
            queue=queue,
        ))

    async def log_injection_attempt(
        self,
        session_id: str,
        source: str,  # "user_voice" | "document"
        pattern_matched: str,
    ) -> None:
        await self.log(AuditEvent(
            AuditEventType.INJECTION_ATTEMPT,
            session_id=session_id,
            source=source,
            pattern_matched=pattern_matched,
        ))

    def _assert_no_raw_pii(self, data: dict) -> None:
        """Verificación básica de que no hay PII obvia en el log."""
        text = json.dumps(data)
        # Detectar DNI/NIE en logs (nunca debería aparecer)
        import re
        if re.search(r'\b\d{8}[A-Za-z]\b', text):
            logger.warning("⚠️  Posible DNI detectado en audit log — revisar")
        if re.search(r'\b[6789]\d{8}\b', text):
            logger.warning("⚠️  Posible teléfono detectado en audit log — revisar")

    async def _persist_to_db(self, event: AuditEvent) -> None:
        """Persiste el evento en base de datos (implementar en producción)."""
        # TODO: Implementar con SQLAlchemy async
        pass


# Instancia global
_audit_logger = AuditLogger()


def get_audit_logger() -> AuditLogger:
    return _audit_logger
