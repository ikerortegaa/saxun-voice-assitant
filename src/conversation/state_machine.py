"""
Orquestador principal de la conversación.
Coordina: STT result → RAG → LLM (guardrails) → TTS → Twilio.
Gestiona la state machine y todos los casos de borde de voz.
"""
import asyncio
import re
import time
from typing import Callable, Optional

from loguru import logger

from src.config import get_settings
from src.models.session import Session, ConversationState
from src.models.rag_models import LLMResponse, RAGAction
from src.rag.retriever import HybridRetriever
from src.rag.guardrails import RAGGuardrails
from src.voice.stt import STTResult, LanguageDetector
from src.voice.tts import TTSService
from src.security.pii_redactor import get_redactor
from src.security.audit_logger import get_audit_logger
from src.handoff.engine import HandoffEngine
from src.conversation.context_manager import SessionContextManager


# Respuestas estándar del sistema (sin LLM)
GREETING = {
    "es": "Buenos días, ha llamado a Saxun. Soy Marta. ¿En qué le puedo ayudar?",
    "ca": "Bon dia, ha trucat a Saxun. Sóc la Marta. En què li puc ajudar?",
    "en": "Good morning, you've reached Saxun. I'm Marta. How can I help you today?",
}
ASR_RETRY = {
    "es": "Le escucho pero no le entiendo bien. ¿Puede repetirlo?",
    "ca": "L'escolto però no l'entenc bé. Pot repetir-ho?",
    "en": "I can hear you but I'm having trouble understanding. Could you repeat that?",
}
ASR_FINAL_FAIL = {
    "es": "Voy a pasarle con uno de nuestros especialistas para atenderle mejor.",
    "ca": "Li passo amb un dels nostres especialistes per atendre'l millor.",
    "en": "I'll transfer you to one of our specialists to better assist you.",
}
SILENCE_FIRST = {
    "es": "¿Sigue ahí? ¿En qué le puedo ayudar?",
    "ca": "Continua aquí? En què li puc ajudar?",
    "en": "Are you still there? How can I help you?",
}
SILENCE_FINAL = {
    "es": "Parece que la línea no va bien. Puede llamarnos de nuevo cuando quiera. ¡Hasta luego!",
    "ca": "Sembla que la línia no va bé. Pot trucar-nos de nou quan vulgui. Fins aviat!",
    "en": "It seems the line isn't working well. You can call us again whenever you like. Goodbye!",
}
CLOSING = {
    "es": "¿Hay algo más en lo que pueda ayudarle?",
    "ca": "Hi ha alguna cosa més en què li pugui ajudar?",
    "en": "Is there anything else I can help you with?",
}
LANGUAGE_CONFIRM = {
    "en": "Of course! We can continue in English. How can I help you?",
    "ca": "Per descomptat! Podem continuar en català. En què li puc ajudar?",
    "es": "Claro que sí. Continuamos en español. ¿En qué le puedo ayudar?",
}

# Patrones para detectar peticiones explícitas de cambio de idioma
_LANG_PATTERNS = [
    (re.compile(r'\b(in\s+english|speak\s+english|english\s+please|can\s+you\s+speak\s+english|atend\s+me\s+in\s+english)\b', re.I), "en"),
    (re.compile(r'\b(inglés|en\s+inglés|hablar\s+en\s+inglés|atender\s+en\s+inglés|puede\s+hablar\s+inglés)\b', re.I), "en"),
    (re.compile(r'\b(en\s+català|en\s+catalán|parlar\s+català|hablar\s+en\s+catalán|catalán\s+por\s+favor)\b', re.I), "ca"),
    (re.compile(r'\b(en\s+español|en\s+castellano|hablar\s+en\s+español|español\s+por\s+favor)\b', re.I), "es"),
]


class ConversationOrchestrator:
    """
    Orquestador central de la conversación por voz.
    Una instancia por llamada activa.
    """

    MAX_ASR_RETRIES = 2
    MAX_UNRESOLVED_TURNS = 3
    MAX_TURN_COUNT = 20
    SILENCE_TIMEOUT_1 = 3.0    # segundos
    SILENCE_TIMEOUT_2 = 6.0

    def __init__(
        self,
        session: Session,
        retriever: HybridRetriever,
        tts: TTSService,
        context_manager: SessionContextManager,
        send_audio_fn: Callable[[bytes], asyncio.Future],
        handoff_engine: HandoffEngine,
    ):
        self._session = session
        self._retriever = retriever
        self._guardrails = RAGGuardrails()
        self._tts = tts
        self._ctx = context_manager
        self._send_audio = send_audio_fn
        self._handoff = handoff_engine
        self._redactor = get_redactor()
        self._audit = get_audit_logger()
        self._lang_detector = LanguageDetector()
        self._settings = get_settings()
        self._processing = False      # lock: evitar procesar 2 utterances a la vez
        self._start_time = time.time()
        self._tts_until: float = 0.0  # timestamp hasta el que el TTS sigue sonando

    # ── Punto de entrada principal ────────────────────────────────────────────

    async def on_call_start(self) -> None:
        """Llamado cuando Twilio abre el Media Stream."""
        await self._audit.log_call_start(
            session_id=self._session.session_id,
            caller_hash=self._session.caller_hash,
            language=self._session.language,
            call_sid=self._session.call_sid,
        )
        # Enviar saludo
        greeting = GREETING.get(self._session.language, GREETING["es"])
        await self._speak(greeting)
        self._session.state = ConversationState.INTENT_CAPTURE
        await self._ctx.save_session(self._session)

    async def on_transcript(self, result: STTResult) -> None:
        """
        Llamado por DeepgramSTT al recibir transcripción final.
        Punto de entrada de cada turno del cliente.
        """
        # Solo procesar transcripciones finales
        if not result.is_final:
            return

        # Ignorar transcripciones mientras el TTS sigue sonando (eco del teléfono)
        if time.time() < self._tts_until:
            logger.debug("TTS activo, ignorando transcripción (posible eco)")
            return

        # Evitar procesar en paralelo
        if self._processing:
            logger.debug("Ya procesando utterance anterior, ignorando")
            return

        text = result.text.strip()
        if not text:
            return

        self._processing = True
        try:
            await self._process_turn(text, result.confidence, result.language)
        except Exception as e:
            logger.exception(f"Error procesando turno: {e}")
            await self._speak_and_handoff("error_tecnico")
        finally:
            self._processing = False

    async def on_barge_in(self, new_text: str, confidence: float) -> None:
        """
        El cliente interrumpe mientras el asistente habla.
        Para TTS y procesa la nueva utterance.
        """
        logger.debug(f"Barge-in detectado: '{new_text[:50]}'")
        self._session.tts_active = False
        # Si hay texto significativo, procesar como nuevo turno
        if len(new_text.split()) >= 2 and confidence >= 0.65:
            await self._process_turn(new_text, confidence)

    async def on_silence(self, silence_duration: float) -> None:
        """Gestiona silencios según timeout."""
        if self._session.state in (
            ConversationState.ENDED,
            ConversationState.HANDOFF_ACTIVE,
        ):
            return

        # No actuar si el TTS sigue sonando (el "silencio" es el cliente escuchando)
        if time.time() < self._tts_until:
            return

        lang = self._session.language
        if silence_duration >= self.SILENCE_TIMEOUT_2:
            await self._speak(SILENCE_FINAL.get(lang, SILENCE_FINAL["es"]))
            await self.on_call_end(reason="silence_timeout")
        elif silence_duration >= self.SILENCE_TIMEOUT_1:
            await self._speak(SILENCE_FIRST.get(lang, SILENCE_FIRST["es"]))

    async def on_call_end(self, reason: str = "normal") -> None:
        """Llamado al colgar o tras timeout."""
        duration = time.time() - self._start_time
        containment = not self._session.handoff_triggered

        await self._audit.log_call_end(
            session_id=self._session.session_id,
            caller_hash=self._session.caller_hash,
            duration_seconds=duration,
            turn_count=self._session.turn_count,
            handoff_triggered=self._session.handoff_triggered,
            containment=containment,
        )
        await self._ctx.end_session(self._session)
        logger.info(
            f"Llamada finalizada: {reason} | duration={duration:.1f}s | "
            f"turns={self._session.turn_count} | containment={containment}"
        )

    # ── Procesamiento de turno ────────────────────────────────────────────────

    async def _process_turn(
        self,
        text: str,
        asr_confidence: float = 1.0,
        detected_lang: Optional[str] = None,
    ) -> None:
        """Pipeline completo para un turno de conversación."""
        lang = self._session.language

        # 1. Verificar ASR confidence
        if asr_confidence < 0.65:
            self._session.failed_asr_count += 1
            if self._session.failed_asr_count >= self.MAX_ASR_RETRIES:
                await self._audit.log(
                    __import__("src.security.audit_logger", fromlist=["AuditEvent"]).AuditEvent(
                        __import__("src.security.audit_logger", fromlist=["AuditEventType"]).AuditEventType.ASR_ERROR,
                        session_id=self._session.session_id,
                        consecutive_failures=self._session.failed_asr_count,
                    )
                )
                await self._speak_and_handoff("fallo_reconocimiento_voz")
                return
            await self._speak(ASR_RETRY.get(lang, ASR_RETRY["es"]))
            return

        self._session.failed_asr_count = 0

        # 2. Detectar cambio de idioma (Deepgram o petición explícita del cliente)
        if detected_lang and detected_lang != lang:
            lang = detected_lang
            self._session.language = lang
            logger.debug(f"Idioma actualizado a: {lang}")

        requested_lang = self._detect_language_request(text)
        if requested_lang and requested_lang != self._session.language:
            self._session.language = requested_lang
            lang = requested_lang
            logger.info(f"Cliente solicitó cambio de idioma a: {lang}")
            await self._speak(LANGUAGE_CONFIRM.get(lang, LANGUAGE_CONFIRM["es"]))
            return

        # 3. Detectar injection attempt en el texto del usuario
        if self._redactor.has_injection_attempt(text):
            await self._audit.log_injection_attempt(
                self._session.session_id, "user_voice", text[:100]
            )
            out_of_scope = {
                "es": "Eso no puedo ayudarle. ¿Le puedo ayudar con algo relacionado con Saxun?",
                "ca": "Això no ho puc ajudar. Li puc ajudar amb alguna cosa relacionada amb Saxun?",
                "en": "I can't help with that. Can I help you with something related to Saxun?",
            }
            await self._speak(out_of_scope.get(lang, out_of_scope["es"]))
            return

        # 4. Redactar PII del texto antes de almacenar en historial
        text_redacted = self._redactor.redact(text)
        self._session.add_turn("user", text, content_redacted=text_redacted)

        # 5. Límite de turnos
        if self._session.turn_count >= self.MAX_TURN_COUNT:
            await self._speak_and_handoff("maximo_turnos_sin_resolucion")
            return

        # 6. Retrieval RAG
        retrieval = await self._retriever.retrieve(
            query=text_redacted,
            language=lang,
        )

        # 7. Logging de retrieval
        await self._audit.log_rag_query(
            session_id=self._session.session_id,
            query_length=len(text_redacted),
            chunks_returned=len(retrieval.chunks),
            top_score=retrieval.chunks[0].score if retrieval.chunks else 0.0,
            evidence_found=bool(retrieval.chunks),
            latency_ms=retrieval.latency_ms,
            doc_ids_accessed=[c.doc_id for c in retrieval.chunks],
        )

        # 8. Generación de respuesta con guardrails
        # on_text_ready: TTS se lanza en cuanto response_text llega del stream,
        # en paralelo con el resto del JSON → reduce silencio percibido ~500-700ms.
        history = self._session.get_history_for_llm()
        text_was_pre_spoken = False

        async def on_text_ready(text: str) -> None:
            nonlocal text_was_pre_spoken
            text_was_pre_spoken = True
            await self._speak(text)

        llm_response = await self._guardrails.generate_response(
            query=text_redacted,
            chunks=retrieval.chunks,
            conversation_history=history,
            language=lang,
            session_id=self._session.session_id,
            on_text_ready=on_text_ready,
        )

        # 9. Registrar turno del asistente
        self._session.add_turn(
            "assistant",
            llm_response.response_text,
            confidence=llm_response.confidence,
            action=llm_response.action.value,
            citations=[c.model_dump() for c in llm_response.citations],
        )

        # 10. Ejecutar acción (no re-hablar si el TTS ya se lanzó vía streaming)
        await self._execute_action(llm_response, text_pre_spoken=text_was_pre_spoken)
        await self._ctx.save_session(self._session)

    async def _execute_action(
        self, response: LLMResponse, text_pre_spoken: bool = False
    ) -> None:
        """Ejecuta la acción del LLM: respond, handoff, no_evidence, clarify.
        text_pre_spoken=True cuando el TTS ya se lanzó vía streaming early-start."""
        if response.action == RAGAction.RESPOND:
            self._session.unresolved_turns = 0
            self._session.state = ConversationState.RESPONSE
            if not text_pre_spoken:
                await self._speak(response.response_text)
            self._session.state = ConversationState.INTENT_CAPTURE

        elif response.action == RAGAction.CLARIFY:
            self._session.state = ConversationState.DISAMBIGUATION
            if not text_pre_spoken:
                await self._speak(response.response_text)

        elif response.action == RAGAction.CONFIRM_STEPS:
            self._session.state = ConversationState.CONFIRMATION
            if not text_pre_spoken:
                await self._speak(response.response_text)

        elif response.action in (RAGAction.NO_EVIDENCE, RAGAction.HANDOFF):
            self._session.unresolved_turns += 1
            if self._session.unresolved_turns >= self.MAX_UNRESOLVED_TURNS:
                response.handoff_reason = "maximo_turnos_sin_resolucion"
            if not text_pre_spoken:
                await self._speak(response.response_text)
            await self._trigger_handoff(response)

    async def _trigger_handoff(self, response: LLMResponse) -> None:
        """Inicia el proceso de derivación a agente humano."""
        self._session.handoff_triggered = True
        self._session.state = ConversationState.HANDOFF_PENDING

        reason = response.handoff_reason or "sin_evidencia_rag"
        await self._audit.log_handoff(
            session_id=self._session.session_id,
            caller_hash=self._session.caller_hash,
            reason=reason,
            priority="alta" if reason in ("reclamacion_formal", "cliente_frustrado") else "media",
            queue=self._handoff.get_queue(reason),
        )

        # Transferir llamada
        await self._handoff.execute_handoff(
            session=self._session,
            handoff_reason=reason,
        )
        self._session.state = ConversationState.HANDOFF_ACTIVE

    # ── Helpers de idioma ─────────────────────────────────────────────────────

    @staticmethod
    def _detect_language_request(text: str) -> Optional[str]:
        """Devuelve el código de idioma si el cliente pide cambiar de idioma, o None."""
        for pattern, lang_code in _LANG_PATTERNS:
            if pattern.search(text):
                return lang_code
        return None

    # ── Audio helpers ─────────────────────────────────────────────────────────

    async def _speak(self, text: str) -> None:
        """Sintetiza y envía audio al cliente."""
        if not text.strip():
            return
        self._session.tts_active = True
        audio = await self._tts.synthesize(text, self._session.language)
        if audio:
            # μ-law 8kHz = 8000 bytes/s → estimar duración de reproducción + margen
            playback_secs = len(audio) / 8000 + 0.5
            self._tts_until = time.time() + playback_secs
            await self._send_audio(audio)
        self._session.tts_active = False

    async def _speak_and_handoff(self, reason: str) -> None:
        """Dice mensaje de derivación y ejecuta handoff."""
        lang = self._session.language
        texts = {
            "error_tecnico": {
                "es": "Disculpe, he tenido un problema técnico. Le paso con un compañero ahora mismo.",
                "ca": "Disculpi, he tingut un problema tècnic. Li passo amb un company ara.",
                "en": "I'm sorry, I've had a technical issue. Let me transfer you right away.",
            },
            "fallo_reconocimiento_voz": {
                "es": "Voy a pasarle con un especialista para atenderle mejor.",
                "ca": "Li passo amb un especialista per atendre'l millor.",
                "en": "I'll transfer you to a specialist to better assist you.",
            },
            "maximo_turnos_sin_resolucion": {
                "es": "Para resolver esto correctamente le paso con uno de nuestros especialistas.",
                "ca": "Per resoldre això correctament li passo amb un dels nostres especialistes.",
                "en": "To resolve this properly I'll transfer you to one of our specialists.",
            },
        }
        text = texts.get(reason, texts["error_tecnico"]).get(lang, texts["error_tecnico"]["es"])
        await self._speak(text)
        from src.models.rag_models import LLMResponse, RAGAction
        await self._trigger_handoff(LLMResponse(
            response_text=text,
            action=RAGAction.HANDOFF,
            handoff_reason=reason,
            language=lang,
        ))

