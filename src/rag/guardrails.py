"""
Guardrails del sistema RAG.
Aplica umbrales de confianza, detecta alucinaciones y construye
el prompt anti-alucinación para OpenAI gpt-4o-mini.
"""
import asyncio
import json
import re
import time
from typing import Callable, Awaitable, Optional

from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from loguru import logger

from src.config import get_settings
from src.models.rag_models import Chunk, LLMResponse, RAGAction, Citation
from src.security.pii_redactor import get_redactor


# ── System prompt (no modificar sin validar en golden dataset) ────────────────
SYSTEM_PROMPT = """Eres Marta, agente de atención al cliente de Saxun. Atiendes llamadas telefónicas.
Habla exactamente como lo haría un agente humano: natural, empática, conversacional.

REGLAS ABSOLUTAS (incumplirlas causa fallo crítico):
1. SOLO responde con información que esté EXPLÍCITAMENTE en los DOCUMENTOS DE REFERENCIA.
2. Si la información NO está en los documentos, establece evidence_found=false y action=no_evidence.
3. NUNCA inventes precios, fechas, nombres, números de referencia ni especificaciones.
4. NUNCA digas "como IA", "como asistente virtual", "según mi conocimiento general" ni frases similares.
5. NO mezcles información de documentos distintos. Usa el documento más relevante para la consulta.
   Si la pregunta toca temas de documentos distintos, responde el más relevante y pregunta si quiere el otro.
6. TONO Y LONGITUD: habla como un agente humano real. 2-3 frases naturales. Si la respuesta es completa y
   parece que el cliente ya tiene lo que necesita, termina con "¿Le puedo ayudar en algo más?"
   Si la consulta requiere más aclaración, haz UNA pregunta concreta.
7. Si la consulta es sobre reclamación formal, cancelación, datos legales → action=handoff.
8. Si el cliente está claramente frustrado o insatisfecho → action=handoff.
9. Confirma siempre antes de dar instrucciones de más de 3 pasos.
10. Usa conectores naturales: "Claro que sí", "Por supuesto", "Mire", "Entiendo". Evita tecnicismos.

FORMATO DE RESPUESTA (JSON estricto, sin markdown):
{
  "response_text": "Texto que se verbalizará al cliente (2-3 frases naturales)",
  "confidence": 0.0 a 1.0,
  "action": "respond" | "handoff" | "no_evidence" | "clarify" | "confirm_steps",
  "evidence_found": true | false,
  "citations": [{"chunk_id": "...", "doc_title": "...", "section": "..."}],
  "handoff_reason": null | "reclamacion_formal" | "cliente_frustrado" | "sin_evidencia_rag" | "consulta_legal" | "solicitud_cancelacion",
  "needs_confirmation": false,
  "language": "es" | "ca" | "en"
}"""


HANDOFF_TRIGGERS = [
    (r'\breclamaci[oó]n\s+formal\b', "reclamacion_formal"),
    (r'\bquiero\s+(?:poner|presentar|hacer)\s+una\s+queja\b', "reclamacion_formal"),
    (r'\bdenunci[ar]?\b', "reclamacion_formal"),
    (r'\babogado\b|\bdemanda\b|\bjuzgado\b', "consulta_legal"),
    (r'\bdar(?:me)?\s+de\s+baja\b|\bcancelar\s+(?:el|mi)\s+contrato\b', "solicitud_cancelacion"),
    (r'\b(?:muy\s+)?(?:enfadad[oa]|indignado|hartísimo|furioso)\b', "cliente_frustrado"),
    (r'\bno\s+(?:me\s+)?(?:está[is]?\s+)?ayudand[oa]\b', "cliente_frustrado"),
    (r'\bagente\s+humano\b|\bpersona\s+real\b|\bhablar\s+con\s+(?:un|una)\s+persona\b', "solicitud_agente"),
]


class RAGGuardrails:
    """
    Orquesta el pipeline RAG → LLM con guardrails completos:
    1. Detección de triggers de handoff inmediato
    2. Construcción del prompt con contexto RAG
    3. Llamada a OpenAI gpt-4o-mini
    4. Validación del output (confianza, alucinación, PII)
    5. Post-processing y decisión de acción
    """

    def __init__(self):
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_llm_model          # gpt-4o-mini
        self._conf_threshold = settings.rag_confidence_threshold        # 0.65
        self._high_conf_threshold = settings.rag_high_confidence_threshold  # 0.85
        self._redactor = get_redactor()

    async def generate_response(
        self,
        query: str,
        chunks: list[Chunk],
        conversation_history: list[dict],
        language: str = "es",
        session_id: str = "",
        on_text_ready: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> LLMResponse:
        """
        Pipeline completo: query + chunks → respuesta validada.
        Si on_text_ready se proporciona, se llama en cuanto el response_text
        está disponible en el stream del LLM (reduce latencia percibida).
        """
        # 1. Verificar modo emergencia
        settings = get_settings()
        if settings.emergency_mode:
            return self._emergency_response(language)

        # 2. Detección de handoff inmediato (sin llamar al LLM)
        immediate_handoff = self._check_immediate_handoff(query)
        if immediate_handoff:
            return LLMResponse(
                response_text=self._handoff_text(immediate_handoff, language),
                confidence=1.0,
                action=RAGAction.HANDOFF,
                evidence_found=False,
                handoff_reason=immediate_handoff,
                language=language,
            )

        # 3. Construir contexto RAG
        rag_context = self._build_rag_context(chunks)
        # RRF scores máximos son ~0.016 (1/61) — umbral ajustado a escala RRF
        evidence_found = bool(chunks) and any(c.score > 0.005 for c in chunks)

        # 4. Llamar a gpt-4o-mini (streaming si hay callback, no-streaming si no)
        if on_text_ready:
            raw_response = await self._call_llm_streaming(
                query=query,
                rag_context=rag_context,
                history=conversation_history,
                language=language,
                on_text_ready=on_text_ready,
            )
        else:
            raw_response = await self._call_llm(
                query=query,
                rag_context=rag_context,
                history=conversation_history,
                language=language,
            )

        # 5. Parsear respuesta estructurada
        llm_response = self._parse_llm_response(raw_response, chunks, language)
        llm_response.evidence_found = evidence_found

        # 6. Post-processing guardrails
        llm_response = self._apply_post_guardrails(llm_response, query)

        # 7. Log para debugging
        logger.debug(
            f"[{session_id}] RAG response: "
            f"action={llm_response.action.value} "
            f"confidence={llm_response.confidence:.2f} "
            f"evidence={llm_response.evidence_found}"
        )

        return llm_response

    # ── LLM call ─────────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=5))
    async def _call_llm(
        self,
        query: str,
        rag_context: str,
        history: list[dict],
        language: str,
    ) -> str:
        user_prompt = self._build_user_prompt(query, rag_context, language)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history[-8:],  # Máximo 4 turnos de historial (8 mensajes)
            {"role": "user", "content": user_prompt},
        ]

        start = time.time()
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=0.2,
            max_tokens=150,         # 2-3 frases de voz (~80-100 tokens texto + JSON overhead)
            response_format={"type": "json_object"},
            timeout=8.0,
        )
        latency = (time.time() - start) * 1000
        logger.debug(f"OpenAI latency: {latency:.0f}ms")

        return response.choices[0].message.content

    async def _call_llm_streaming(
        self,
        query: str,
        rag_context: str,
        history: list[dict],
        language: str,
        on_text_ready: Callable[[str], Awaitable[None]],
    ) -> str:
        """
        Llama al LLM con streaming. En cuanto el campo response_text está completo
        en el buffer JSON parcial, lanza on_text_ready como tarea concurrente para
        que el TTS empiece mientras el LLM termina de generar el resto del JSON.
        """
        user_prompt = self._build_user_prompt(query, rag_context, language)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history[-8:],
            {"role": "user", "content": user_prompt},
        ]

        buffer = ""
        tts_task: asyncio.Task | None = None
        start = time.time()

        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.2,
                max_tokens=150,
                response_format={"type": "json_object"},
                stream=True,
                timeout=8.0,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                if not delta:
                    continue
                buffer += delta

                # Extraer response_text en cuanto su valor está completo en el buffer
                if tts_task is None:
                    m = re.search(
                        r'"response_text"\s*:\s*"((?:[^"\\]|\\.)*)"', buffer
                    )
                    if m:
                        text = m.group(1).replace('\\"', '"').replace("\\n", " ")
                        tts_task = asyncio.create_task(on_text_ready(text))

            latency = (time.time() - start) * 1000
            logger.debug(
                f"OpenAI streaming latency: {latency:.0f}ms "
                f"(early_tts={'yes' if tts_task else 'no'})"
            )

            # Esperar TTS si todavía está en marcha
            if tts_task:
                await tts_task

        except Exception as e:
            logger.warning(f"LLM streaming falló ({e}), usando llamada normal")
            if tts_task and not tts_task.done():
                tts_task.cancel()
            # Fallback a llamada no-streaming (sin retry por simplicidad)
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.2,
                max_tokens=150,
                response_format={"type": "json_object"},
                timeout=8.0,
            )
            buffer = response.choices[0].message.content

        return buffer

    # ── Builders ─────────────────────────────────────────────────────────────

    def _build_rag_context(self, chunks: list[Chunk]) -> str:
        if not chunks:
            return "No se encontró información relevante en los documentos de Saxun."

        parts = []
        for i, chunk in enumerate(chunks, 1):
            doc_title = chunk.metadata.get("doc_title", chunk.doc_id)
            parts.append(
                f"[DOCUMENTO {i} | ID: {chunk.chunk_id} | "
                f"Fuente: {doc_title} | Sección: {chunk.section}]\n"
                f"{chunk.content}"
            )
        return "\n\n---\n\n".join(parts)

    def _build_user_prompt(self, query: str, rag_context: str, language: str) -> str:
        lang_instruction = {
            "es": "Responde en español.",
            "ca": "Respon en català.",
            "en": "Respond in English.",
        }.get(language, "Responde en español.")

        return (
            f"DOCUMENTOS DE REFERENCIA:\n{rag_context}\n\n"
            f"CONSULTA DEL CLIENTE: {query}\n\n"
            f"{lang_instruction} Responde SOLO con el JSON indicado."
        )

    # ── Parsers y validadores ─────────────────────────────────────────────────

    def _parse_llm_response(
        self,
        raw: str,
        chunks: list[Chunk],
        language: str,
    ) -> LLMResponse:
        """Parsea y valida el JSON del LLM. Tiene fallbacks robustos."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"LLM devolvió JSON inválido: {raw[:200]}")
            return self._fallback_response(language)

        # Validar acción
        try:
            action = RAGAction(data.get("action", "respond"))
        except ValueError:
            action = RAGAction.RESPOND

        # Construir citas (solo si los chunk_ids existen realmente)
        chunk_id_map = {c.chunk_id: c for c in chunks}
        citations = []
        for cite in data.get("citations", []):
            cid = cite.get("chunk_id", "")
            if cid in chunk_id_map:
                c = chunk_id_map[cid]
                citations.append(Citation(
                    chunk_id=cid,
                    doc_id=c.doc_id,
                    doc_title=cite.get("doc_title", c.metadata.get("doc_title", "")),
                    section=cite.get("section", c.section),
                    relevance_score=c.score,
                ))

        return LLMResponse(
            response_text=data.get("response_text", self._no_info_text(language)),
            confidence=float(data.get("confidence", 0.5)),
            action=action,
            citations=citations,
            evidence_found=data.get("evidence_found", False),
            language=data.get("language", language),
            handoff_reason=data.get("handoff_reason"),
            needs_confirmation=data.get("needs_confirmation", False),
            raw_response=raw,
        )

    def _apply_post_guardrails(self, response: LLMResponse, query: str) -> LLMResponse:
        """Aplica guardrails tras el LLM. Orden: confianza → alucinación → PII → longitud."""

        # 1. Sin evidencia → forzar no_evidence si el LLM intentó responder
        if not response.evidence_found and response.action == RAGAction.RESPOND:
            response.action = RAGAction.NO_EVIDENCE
            response.confidence = 0.0

        # 2. Confianza baja → derivar
        if (response.confidence < self._conf_threshold
                and response.action == RAGAction.RESPOND):
            response.action = RAGAction.HANDOFF
            response.handoff_reason = "baja_confianza"

        # 3. Indicadores de alucinación en el texto
        if self._redactor.has_hallucination_indicators(response.response_text):
            logger.warning("Indicador de alucinación detectado en respuesta → derivar")
            response.action = RAGAction.NO_EVIDENCE
            response.confidence = 0.0

        # 4. PII en respuesta (nunca debería ocurrir pero verificamos)
        if self._redactor.contains_pii(response.response_text):
            logger.error("PII detectado en respuesta LLM → redactando")
            response.response_text = self._redactor.redact(response.response_text)

        # 5. Longitud para voz (max ~50 palabras = 2 frases)
        response.response_text = self._enforce_voice_length(response.response_text)

        return response

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _check_immediate_handoff(self, query: str) -> Optional[str]:
        """Detecta triggers de handoff sin llamar al LLM (reglas explícitas)."""
        query_lower = query.lower()
        for pattern, reason in HANDOFF_TRIGGERS:
            if re.search(pattern, query_lower):
                logger.info(f"Handoff inmediato por regla: {reason}")
                return reason
        return None

    @staticmethod
    def _enforce_voice_length(text: str, max_words: int = 60) -> str:
        """Trunca respuestas demasiado largas para voz."""
        words = text.split()
        if len(words) <= max_words:
            return text
        # Truncar en la última frase completa que cabe
        truncated = " ".join(words[:max_words])
        # Buscar el último punto para cortar limpio
        last_dot = max(truncated.rfind("."), truncated.rfind("?"), truncated.rfind("!"))
        if last_dot > len(truncated) * 0.5:
            return truncated[:last_dot + 1]
        return truncated + "."

    @staticmethod
    def _handoff_text(reason: str, language: str) -> str:
        texts = {
            "reclamacion_formal": {
                "es": "Entiendo que desea registrar una reclamación formal. Le paso con nuestro equipo de incidencias ahora mismo.",
                "ca": "Entenc que vol registrar una reclamació formal. Li passo amb el nostre equip ara mateix.",
                "en": "I understand you'd like to file a formal complaint. I'll transfer you to our team right away.",
            },
            "consulta_legal": {
                "es": "Para este tipo de consulta necesitará hablar con nuestro departamento especializado. Le transfiero ahora.",
                "ca": "Per a aquest tipus de consulta necessitarà parlar amb el nostre departament especialitzat. Li passo ara.",
                "en": "For this type of inquiry you'll need to speak with our specialized department. Transferring you now.",
            },
            "solicitud_cancelacion": {
                "es": "Para gestionar la baja o cancelación le paso directamente con el equipo responsable.",
                "ca": "Per gestionar la baixa o cancel·lació li passo directament amb l'equip responsable.",
                "en": "To handle your cancellation I'll transfer you to the responsible team.",
            },
            "cliente_frustrado": {
                "es": "Entiendo su situación y lamento los inconvenientes. Le paso con un responsable para atenderle personalmente.",
                "ca": "Entenc la seva situació i lamento els inconvenients. Li passo amb un responsable.",
                "en": "I understand your situation and I'm sorry for the inconvenience. Let me transfer you to a supervisor.",
            },
        }
        lang_texts = texts.get(reason, texts["reclamacion_formal"])
        return lang_texts.get(language, lang_texts["es"])

    @staticmethod
    def _no_info_text(language: str) -> str:
        texts = {
            "es": "No tengo esa información en este momento. ¿Le paso con uno de nuestros especialistas?",
            "ca": "No tinc aquesta informació en aquest moment. Li passo amb un dels nostres especialistes?",
            "en": "I don't have that information right now. Shall I transfer you to one of our specialists?",
        }
        return texts.get(language, texts["es"])

    @staticmethod
    def _fallback_response(language: str) -> LLMResponse:
        texts = {
            "es": "Disculpe, he tenido un problema técnico. Le paso con un compañero ahora mismo.",
            "ca": "Disculpi, he tingut un problema tècnic. Li passo amb un company ara mateix.",
            "en": "I'm sorry, I've had a technical issue. Let me transfer you to a colleague right away.",
        }
        return LLMResponse(
            response_text=texts.get(language, texts["es"]),
            confidence=0.0,
            action=RAGAction.HANDOFF,
            evidence_found=False,
            handoff_reason="error_tecnico",
            language=language,
        )

    @staticmethod
    def _emergency_response(language: str) -> LLMResponse:
        texts = {
            "es": "Disculpe, estamos experimentando problemas técnicos. Le paso con un agente ahora mismo.",
            "ca": "Disculpi, estem experimentant problemes tècnics. Li passo amb un agent ara mateix.",
            "en": "I'm sorry, we're experiencing technical issues. I'll transfer you to an agent right away.",
        }
        return LLMResponse(
            response_text=texts.get(language, texts["es"]),
            confidence=0.0,
            action=RAGAction.HANDOFF,
            evidence_found=False,
            handoff_reason="modo_emergencia",
            language=language,
        )
