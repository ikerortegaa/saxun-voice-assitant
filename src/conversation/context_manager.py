"""
Gestor de contexto de sesión.
Almacena y recupera sesiones en Redis (TTL 30 min).
Las sesiones son efímeras — sin PII persistida.
"""
import json
import uuid
import hashlib
from datetime import datetime
from typing import Optional

import redis.asyncio as aioredis
from loguru import logger

from src.config import get_settings
from src.models.session import Session, ConversationState


class SessionContextManager:
    """
    Gestiona el ciclo de vida de las sesiones de llamada en Redis.
    Redis como almacenamiento principal (TTL 30 min, auto-expiry).
    """

    SESSION_PREFIX = "session:"

    def __init__(self, redis_client: aioredis.Redis):
        self._redis = redis_client
        self._settings = get_settings()

    async def create_session(
        self,
        call_sid: str,
        caller_number: str,
        stream_sid: str = "",
    ) -> Session:
        """Crea una nueva sesión para una llamada entrante."""
        session_id = f"sess_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        caller_hash = self._hash_caller(caller_number)

        session = Session(
            session_id=session_id,
            call_sid=call_sid,
            stream_sid=stream_sid,
            caller_hash=caller_hash,
            state=ConversationState.GREETING,
        )

        await self._save(session)
        logger.info(f"Sesión creada: {session_id} (call_sid={call_sid})")
        return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """Recupera una sesión existente."""
        key = self._key(session_id)
        raw = await self._redis.get(key)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return Session(**data)
        except Exception as e:
            logger.error(f"Error deserializando sesión {session_id}: {e}")
            return None

    async def get_session_by_call_sid(self, call_sid: str) -> Optional[Session]:
        """Busca sesión por call_sid de Twilio."""
        mapping_key = f"call_sid:{call_sid}"
        session_id = await self._redis.get(mapping_key)
        if not session_id:
            return None
        return await self.get_session(session_id.decode())

    async def save_session(self, session: Session) -> None:
        """Persiste la sesión actualizada en Redis."""
        await self._save(session)
        # Mantener mapping call_sid → session_id
        if session.call_sid:
            mapping_key = f"call_sid:{session.call_sid}"
            await self._redis.setex(
                mapping_key,
                self._settings.redis_session_ttl,
                session.session_id,
            )

    async def end_session(self, session: Session) -> None:
        """Marca la sesión como finalizada y elimina de Redis (GDPR)."""
        session.state = ConversationState.ENDED
        # No persiste el historial completo — solo metadatos de auditoría
        logger.info(
            f"Sesión finalizada: {session.session_id} | "
            f"turns={session.turn_count} | "
            f"handoff={session.handoff_triggered}"
        )
        # Eliminar inmediatamente de Redis (datos efímeros)
        await self._redis.delete(self._key(session.session_id))
        if session.call_sid:
            await self._redis.delete(f"call_sid:{session.call_sid}")

    async def update_stream_sid(self, session: Session, stream_sid: str) -> None:
        """Actualiza el stream_sid cuando Twilio lo notifica."""
        session.stream_sid = stream_sid
        await self._save(session)

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _save(self, session: Session) -> None:
        key = self._key(session.session_id)
        # Serializar con solo los campos necesarios para reconstituir
        data = session.model_dump(mode="json")
        await self._redis.setex(
            key,
            self._settings.redis_session_ttl,
            json.dumps(data, default=str),
        )

    def _key(self, session_id: str) -> str:
        return f"{self.SESSION_PREFIX}{session_id}"

    @staticmethod
    def _hash_caller(caller_number: str) -> str:
        """Hash SHA-256 del número de teléfono (nunca se almacena el real)."""
        return hashlib.sha256(caller_number.encode()).hexdigest()[:32]
