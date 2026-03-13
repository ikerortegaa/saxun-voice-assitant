"""
STT — Speech-to-Text con Deepgram Nova-2 en modo streaming.
Recibe audio μ-law 8kHz de Twilio y devuelve transcripciones en tiempo real.
Fallback: Azure Speech Services (si AZURE_SPEECH_KEY configurado).
"""
import asyncio
import base64
from dataclasses import dataclass, field
from typing import Callable, Optional

from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)
from loguru import logger

from src.config import get_settings


@dataclass
class STTResult:
    text: str
    confidence: float
    is_final: bool
    language: str = "es"
    words: list[dict] = field(default_factory=list)

    @property
    def is_reliable(self) -> bool:
        """True si la transcripción es suficientemente confiable."""
        return self.confidence >= 0.70 and bool(self.text.strip())


class DeepgramSTT:
    """
    Streaming STT con Deepgram Nova-2.
    Ciclo de vida: una instancia por llamada telefónica.
    """

    def __init__(
        self,
        on_transcript: Callable[[STTResult], None],
        language: str = "es",
    ):
        settings = get_settings()
        self._api_key = settings.deepgram_api_key
        self._model = settings.deepgram_model   # nova-2
        self._language = language
        self._on_transcript = on_transcript
        self._connection = None
        self._client = None
        self._is_connected = False
        self._final_transcript = ""

    async def connect(self) -> None:
        """Abre la conexión WebSocket con Deepgram."""
        config = DeepgramClientOptions(
            verbose=False,
            options={"keepalive": "true"},
        )
        self._client = DeepgramClient(self._api_key, config)
        self._connection = self._client.listen.asyncwebsocket.v("1")

        # Registrar handlers de eventos
        self._connection.on(
            LiveTranscriptionEvents.Transcript, self._handle_transcript
        )
        self._connection.on(
            LiveTranscriptionEvents.Error, self._handle_error
        )
        self._connection.on(
            LiveTranscriptionEvents.Close, self._handle_close
        )

        # Opciones de transcripción
        options = LiveOptions(
            model=self._model,
            language=self._language,
            smart_format=True,          # Puntuación y formato automático
            interim_results=True,       # Resultados intermedios para barge-in
            utterance_end_ms="1000",    # 1s de silencio = fin de utterance
            vad_events=True,            # Eventos de actividad de voz
            endpointing=400,            # Detectar fin de turno en 400ms
            encoding="mulaw",           # Formato de audio de Twilio
            sample_rate=8000,           # Twilio usa 8kHz
            channels=1,
        )

        started = await self._connection.start(options)
        if not started:
            logger.error(f"Deepgram start() devolvió False — opciones enviadas: {options}")
            raise RuntimeError("No se pudo conectar con Deepgram STT")

        self._is_connected = True
        logger.info(f"Deepgram STT conectado (model={self._model}, lang={self._language})")

    async def send_audio(self, audio_b64: str) -> None:
        """Envía un chunk de audio (base64 μ-law de Twilio) a Deepgram."""
        if not self._is_connected or not self._connection:
            return
        try:
            audio_bytes = base64.b64decode(audio_b64)
            await self._connection.send(audio_bytes)
        except Exception as e:
            logger.warning(f"Error enviando audio a Deepgram: {e}")

    async def disconnect(self) -> None:
        """Cierra la conexión limpiamente."""
        if self._connection and self._is_connected:
            await self._connection.finish()
            self._is_connected = False
            logger.debug("Deepgram STT desconectado")

    # ── Handlers Deepgram ─────────────────────────────────────────────────────

    async def _handle_transcript(self, _client, result, **kwargs) -> None:
        """Callback invocado por Deepgram al recibir transcripción."""
        try:
            sentence = result.channel.alternatives[0]
            text = sentence.transcript.strip()
            if not text:
                return

            confidence = float(sentence.confidence) if sentence.confidence else 0.5
            is_final = result.is_final

            stt_result = STTResult(
                text=text,
                confidence=confidence,
                is_final=is_final,
                language=self._language,
                words=[
                    {"word": w.word, "confidence": w.confidence}
                    for w in (sentence.words or [])
                ],
            )

            if is_final:
                self._final_transcript = text
                logger.debug(
                    f"STT final: '{text}' (confidence={confidence:.2f})"
                )

            # Notificar al orquestador
            self._on_transcript(stt_result)

        except (AttributeError, IndexError) as e:
            logger.debug(f"STT result vacío o malformado: {e}")

    async def _handle_error(self, _client, error, **kwargs) -> None:
        logger.error(f"Error Deepgram: {error}")

    async def _handle_close(self, _client, close, **kwargs) -> None:
        self._is_connected = False
        logger.debug("Conexión Deepgram cerrada")

    @property
    def is_connected(self) -> bool:
        return self._is_connected


class LanguageDetector:
    """
    Detecta el idioma del cliente en los primeros turnos de la conversación.
    Usa el texto de Deepgram (ya que Nova-2 puede detectar idioma).
    """

    SUPPORTED_LANGS = {"es", "ca", "en"}

    def detect(self, text: str, current_lang: str = "es") -> str:
        try:
            from langdetect import detect
            detected = detect(text)
            # Mapear catalán (langdetect devuelve 'ca')
            if detected in self.SUPPORTED_LANGS:
                return detected
            # Si detecta portugués puede ser catalán (similitud)
            if detected == "pt" and self._has_catalan_markers(text):
                return "ca"
        except Exception:
            pass
        return current_lang

    @staticmethod
    def _has_catalan_markers(text: str) -> bool:
        catalan_words = {"bon", "dia", "gràcies", "hola", "el", "la", "els", "les",
                         "tinc", "vull", "com", "que", "per", "amb"}
        words = set(text.lower().split())
        return len(words & catalan_words) >= 2
