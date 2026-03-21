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
from src.models.rag_models import LLMResponse, RAGAction, Chunk
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
    "es": "Buenos días, ha llamado a Saxun. Soy Laura. ¿En qué le puedo ayudar?",
    "ca": "Bon dia, ha trucat a Saxun. Sóc la Laura. En què li puc ajudar?",
    "en": "Good morning, you've reached Saxun. I'm Laura. How can I help you today?",
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

# Patrón para detectar número de pedido en el texto del cliente
# Detecta: "pedido 1234", "orden 5678", "referencia 9012", "SO0042", "S00042"
_ORDER_PATTERN = re.compile(
    r'(?:'
    r'(?:pedido|orden|referencia|número|num\.?)[^\d]{0,20}(\d{4,10})'  # pedido 1234, referencia es 9999
    r'|'
    r'\b(S[O0]\d{4,8})\b'  # SO0042 o S00042
    r')',
    re.IGNORECASE,
)

# Detecta intención de consultar un pedido SIN número (activa flujo de 2 turnos)
_ORDER_INTENT_PATTERN = re.compile(
    r'\b(?:pedido|estado\s+del\s+pedido|consultar\s+(?:el\s+)?pedido|'
    r'mi\s+pedido|mi\s+orden|estado\s+de\s+(?:mi\s+)?(?:pedido|orden|envío)|'
    r'dónde\s+está\s+(?:mi\s+)?(?:pedido|orden|paquete|envío)|'
    r'seguimiento|cuando\s+llega|cuando\s+llega|no\s+ha\s+llegado|'
    r'no\s+llegó|no\s+me\s+ha\s+llegado|entrega|envío)\b',
    re.IGNORECASE,
)

def _extract_order_ref_from_reply(text: str) -> Optional[str]:
    """
    Extrae referencia de pedido de la respuesta STT del cliente.

    Maneja tres casos reales de reconocimiento de voz:
      - "1234"             → "1234"  (número directo ≥4 dígitos)
      - "S 0 0 0 16"       → "S0016" (referencia deletreada carácter a carácter)
      - "pedido número 16" → "16"    (número corto, demo con pedidos pequeños)

    Los pedidos en Odoo de demo suelen ser SO0001…SO0099, por eso aceptamos
    números de 2+ dígitos como último recurso.
    """
    clean = re.sub(r'[^\w\s]', ' ', text.upper()).strip()

    # 1. Número largo directo (≥4 dígitos) — caso de producción
    m = re.search(r'\b(\d{4,10})\b', clean)
    if m:
        return m.group(1)

    # 2. Reconstruir secuencia deletreada: tokens del tipo S/O/SO + dígitos
    # Ejemplo: "S 0 0 0 16" → tokens = ["S","0","0","0","16"] → "S0016"
    tokens = clean.split()
    n = len(tokens)
    best: Optional[str] = None
    for start in range(n):
        tok0 = tokens[start]
        if not (re.fullmatch(r'[SO]', tok0) or re.fullmatch(r'\d{1,3}', tok0)):
            continue
        seq: list[str] = []
        i = start
        # Consumir prefijo S/O de hasta 2 letras separadas ("S O" → "SO")
        while i < n and re.fullmatch(r'[SO]', tokens[i]) and len(seq) < 2:
            seq.append(tokens[i])
            i += 1
        # Consumir dígitos individuales o cortos
        while i < n and re.fullmatch(r'\d{1,3}', tokens[i]):
            seq.append(tokens[i])
            i += 1
        if len(seq) >= 2:
            candidate = ''.join(seq)
            if re.match(r'^[A-Z]{0,2}\d{2,}$', candidate):
                if best is None or len(candidate) > len(best):
                    best = candidate

    if best:
        return best

    # 3. Número corto (2-3 dígitos) — para pedidos de demo pequeños
    m = re.search(r'\b(\d{2,3})\b', clean)
    if m:
        return m.group(1)

    return None

# Preguntas de Laura para pedir el nº de pedido
_ASK_ORDER_NUMBER = {
    "es": "Por supuesto. ¿Puede decirme el número de pedido?",
    "ca": "Per descomptat. Pot dir-me el número de comanda?",
    "en": "Of course. Could you tell me your order number?",
}
# Respuesta cuando el pedido no se encuentra
_ORDER_NOT_FOUND = {
    "es": "No he podido encontrar ese pedido. ¿Puede confirmar el número de pedido?",
    "ca": "No he pogut trobar aquesta comanda. Pot confirmar el número de comanda?",
    "en": "I couldn't find that order. Could you confirm the order number?",
}
# Confirmación antes del lookup (evita silencio y pronuncia el nº correctamente)
_LOOKING_UP_ORDER = {
    "es": "Un momento, voy a consultar los detalles del pedido {ref}.",
    "ca": "Un moment, vaig a consultar els detalls de la comanda {ref}.",
    "en": "One moment, let me look up the details for order {ref}.",
}


def _format_order_ref_for_tts(ref: str) -> str:
    """
    Formatea una referencia de pedido para que el TTS la pronuncie carácter a carácter.

    Ejemplos:
      'SO0007' → 'S-O-0-0-0-7'  → TTS: "ese-o-cero-cero-cero-siete"
      'SO16'   → 'S-O-1-6'      → TTS: "ese-o-uno-seis"
      '7'      → '7'            → TTS: "siete" (número puro, sin separadores)
    """
    ref = ref.upper()
    if ref.isdigit():
        return ref  # número puro: el TTS lo lee como número directamente
    return "-".join(ref)

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
        self._pending_transcript: Optional[STTResult] = None  # último transcript mientras se procesaba
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

        # Ignorar transcripciones mientras el TTS sigue sonando (eco del teléfono).
        # Cuando estamos esperando nº de pedido, reducimos el margen a 0.9s
        # (el eco telefónico tarda ~0.8s, el usuario responde al menos 1s después).
        if time.time() < self._tts_until:
            if self._session.awaiting_order_number:
                # En modo respuesta-pedido: solo bloquear durante el eco puro
                echo_only_until = self._tts_until - 1.1   # 2.0s margin → 0.9s echo guard
                if time.time() < echo_only_until:
                    logger.debug(
                        f"TTS activo (modo pedido), ignorando posible eco: '{result.text[:30]}'"
                    )
                    return
                # Pasado el eco puro: procesar normalmente aunque el margen no haya expirado
                logger.debug(
                    f"TTS activo pero esperando nº pedido — procesando: '{result.text[:30]}'"
                )
            else:
                logger.debug(
                    f"TTS activo, ignorando transcripción (posible eco): '{result.text[:30]}'"
                )
                return

        # Evitar procesar en paralelo — guardar el último para procesarlo después
        if self._processing:
            self._pending_transcript = result
            logger.debug(f"Procesando turno anterior, guardando: '{result.text[:40]}'")
            return

        text = result.text.strip()
        if not text:
            return

        self._processing = True
        self._pending_transcript = None
        try:
            await self._process_turn(text, result.confidence, result.language)
        except Exception as e:
            logger.exception(f"Error procesando turno: {e}")
            await self._speak_and_handoff("error_tecnico")
        finally:
            self._processing = False
            # Procesar el transcript pendiente si llegó mientras estábamos ocupados
            if self._pending_transcript:
                pending = self._pending_transcript
                self._pending_transcript = None
                asyncio.create_task(self.on_transcript(pending))

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

        # 2. Detectar cambio de idioma
        #    Fuente 1: Deepgram detect_language (por utterance)
        #    Fuente 2: langdetect sobre el texto (backup, especialmente para catalán)
        if detected_lang and detected_lang != lang:
            lang = detected_lang
            self._session.language = lang
            logger.debug(f"Idioma actualizado vía Deepgram a: {lang}")
        else:
            # Solo aplicar langdetect en los primeros 3 turnos o si el texto es largo
            if self._session.turn_count <= 3 or len(text) > 30:
                inferred = self._lang_detector.detect(text, lang)
                if inferred != lang:
                    self._session.language = inferred
                    lang = inferred
                    logger.debug(f"Idioma actualizado vía langdetect a: {lang}")

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

        # 6. Flujo Odoo:
        #    6a. awaiting_order_number=True → extraer nº de la respuesta del cliente
        #    6b. Número en el texto actual → lookup directo, guardar ref
        #    6c. No hay número pero hay ref guardada + intención de pedido → reusar
        #    6d. No hay número ni ref guardada + intención → preguntar
        odoo_chunk = None
        if self._settings.odoo_enabled:
            if self._session.awaiting_order_number:
                # El cliente responde con el número (sin keyword).
                # Extractor inteligente: "S 0 0 0 16", "0016", "16", etc.
                order_ref = _extract_order_ref_from_reply(text_redacted)
                if order_ref:
                    self._session.awaiting_order_number = False
                    # Confirmar el número en voz alta ANTES del lookup (evita silencio
                    # y pronuncia el código alfanumérico carácter a carácter).
                    ref_spoken = _format_order_ref_for_tts(order_ref)
                    await self._speak(
                        _LOOKING_UP_ORDER.get(lang, _LOOKING_UP_ORDER["es"]).format(ref=ref_spoken)
                    )
                    odoo_chunk = await self._get_odoo_chunk_by_ref(order_ref, lang)
                    if not odoo_chunk:
                        await self._speak(_ORDER_NOT_FOUND.get(lang, _ORDER_NOT_FOUND["es"]))
                        self._session.awaiting_order_number = True
                        await self._ctx.save_session(self._session)
                        return
                    # Guardar para reutilizar en turnos siguientes
                    self._session.current_order_ref = order_ref
                else:
                    logger.debug(
                        f"awaiting_order_number: sin referencia en '{text_redacted[:50]}'"
                    )
                    await self._speak(_ASK_ORDER_NUMBER.get(lang, _ASK_ORDER_NUMBER["es"]))
                    await self._ctx.save_session(self._session)
                    return
            else:
                # Detección directa: número ya mencionado en el texto
                odoo_chunk = await self._get_odoo_chunk(text_redacted, lang)
                if odoo_chunk:
                    # Actualizar ref guardada con el pedido recién mencionado
                    m = _ORDER_PATTERN.search(text_redacted.upper())
                    if m:
                        new_ref = m.group(1) or m.group(2)
                        if new_ref:
                            self._session.current_order_ref = new_ref
                elif self._session.current_order_ref and _ORDER_INTENT_PATTERN.search(text_redacted):
                    # Pregunta de seguimiento sobre el mismo pedido → reusar sin preguntar
                    logger.debug(
                        f"Reutilizando pedido guardado: {self._session.current_order_ref}"
                    )
                    odoo_chunk = await self._get_odoo_chunk_by_ref(
                        self._session.current_order_ref, lang
                    )
                elif _ORDER_INTENT_PATTERN.search(text_redacted):
                    # Sin ref guardada → pedir número
                    await self._speak(_ASK_ORDER_NUMBER.get(lang, _ASK_ORDER_NUMBER["es"]))
                    self._session.awaiting_order_number = True
                    await self._ctx.save_session(self._session)
                    return

        # 7. Retrieval RAG
        # language=None → busca en todos los idiomas (necesario cuando los docs
        # están en es pero el cliente habla en/ca: el LLM traduce en la respuesta)
        retrieval = await self._retriever.retrieve(
            query=text_redacted,
            language=None,
        )

        # Prepend Odoo chunk como contexto de alta relevancia
        if odoo_chunk:
            retrieval.chunks.insert(0, odoo_chunk)

        # 8. Logging de retrieval
        await self._audit.log_rag_query(
            session_id=self._session.session_id,
            query_length=len(text_redacted),
            chunks_returned=len(retrieval.chunks),
            top_score=retrieval.chunks[0].score if retrieval.chunks else 0.0,
            evidence_found=bool(retrieval.chunks),
            latency_ms=retrieval.latency_ms,
            doc_ids_accessed=[c.doc_id for c in retrieval.chunks],
        )

        # 9. Generación de respuesta con guardrails
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

        # 10. Registrar turno del asistente
        self._session.add_turn(
            "assistant",
            llm_response.response_text,
            confidence=llm_response.confidence,
            action=llm_response.action.value,
            citations=[c.model_dump() for c in llm_response.citations],
        )

        # 11. Ejecutar acción (no re-hablar si el TTS ya se lanzó vía streaming)
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

        elif response.action == RAGAction.HANDOFF:
            # Handoff explícito del LLM (reclamación, frustración, legal, cancelación)
            self._session.unresolved_turns += 1
            if not text_pre_spoken:
                await self._speak(response.response_text)
            await self._trigger_handoff(response)

        elif response.action == RAGAction.NO_EVIDENCE:
            # Sin evidencia RAG: dar MAX_UNRESOLVED_TURNS oportunidades antes de derivar
            self._session.unresolved_turns += 1
            if not text_pre_spoken:
                await self._speak(response.response_text)
            if self._session.unresolved_turns >= self.MAX_UNRESOLVED_TURNS:
                response.handoff_reason = "maximo_turnos_sin_resolucion"
                await self._trigger_handoff(response)
            else:
                # Mantener la conversación activa para que el cliente pueda reformular
                self._session.state = ConversationState.INTENT_CAPTURE

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
            # μ-law 8kHz = 8000 bytes/s + 2.0s margen (Twilio buffer + latencia + eco telefónico)
            playback_secs = len(audio) / 8000 + 2.0
            self._tts_until = time.time() + playback_secs
            await self._send_audio(audio)
        self._session.tts_active = False

    # ── Odoo integration ──────────────────────────────────────────────────────

    async def _get_odoo_chunk_by_ref(self, order_ref: str, language: str) -> Optional[Chunk]:
        """Consulta Odoo directamente por referencia (sin necesidad de keyword en texto)."""
        from src.integrations.odoo_client import get_odoo_client
        context_text = await get_odoo_client().get_order_context(order_ref)
        if not context_text:
            return None
        return Chunk(
            chunk_id=f"odoo_{order_ref}",
            doc_id="odoo_erp_live",
            content=context_text,
            section="pedido_en_tiempo_real",
            language=language,
            sensitivity="internal",
            score=0.95,
            metadata={"source": "odoo", "order_ref": order_ref},
        )

    async def _get_odoo_chunk(self, text: str, language: str) -> Optional[Chunk]:
        """
        Si el texto menciona un número de pedido y Odoo está configurado,
        consulta el ERP y devuelve un Chunk con los datos reales del pedido.
        Devuelve None si Odoo no está habilitado o el pedido no se encuentra.
        """
        if not self._settings.odoo_enabled:
            return None

        m = _ORDER_PATTERN.search(text)
        if not m:
            return None

        order_ref = m.group(1) or m.group(2)
        if not order_ref:
            return None

        # Import aquí para evitar ciclos de dependencia en tests
        from src.integrations.odoo_client import get_odoo_client
        context_text = await get_odoo_client().get_order_context(order_ref)

        if not context_text:
            return None

        return Chunk(
            chunk_id=f"odoo_{order_ref}",
            doc_id="odoo_erp_live",
            content=context_text,
            section="pedido_en_tiempo_real",
            language=language,
            sensitivity="internal",
            score=0.95,  # Alta prioridad — datos reales del ERP
            metadata={"source": "odoo", "order_ref": order_ref},
        )

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

