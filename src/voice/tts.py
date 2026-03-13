"""
TTS — Text-to-Speech.

Provider configurado en .env → TTS_PROVIDER:
  "azure"      → Azure Cognitive Services Speech ← RECOMENDADO
                 ElviraNeural: la mejor voz española para IVR/teléfono.
                 Output directo μ-law 8kHz — sin conversión. ~$15/1M chars.
  "openai"     → OpenAI TTS (tts-1) — buena alternativa, ~$15/1M chars.
  "elevenlabs" → ElevenLabs (calidad premium, ~$30/1M chars, requiere plan pago)

Fallback: azure/elevenlabs → openai → silencio breve (no corta la llamada).

Salida: audio μ-law 8kHz mono — formato nativo de Twilio Media Streams.
"""
try:
    import audioop  # Python ≤ 3.12
except ModuleNotFoundError:
    import audioop_lts as audioop  # Python 3.13+ (audioop-lts package)
import base64
import io
import random

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import get_settings

FILLER_TEXTS = {
    "es": ["Un momento...", "Déjeme consultar...", "Enseguida le digo..."],
    "ca": ["Un moment...", "Deixi'm consultar...", "Ara li dic..."],
    "en": ["One moment...", "Let me check...", "I'll be right with you..."],
}


class TTSService:
    """
    Servicio TTS con selección de provider y fallback.
    Una instancia por aplicación (compartida entre sesiones).
    """

    def __init__(self):
        settings = get_settings()
        self._provider = settings.tts_provider.lower()
        self._openai = OpenAITTS()
        self._azure = AzureSpeechTTS() if self._provider == "azure" else None
        self._elevenlabs = ElevenLabsTTS() if self._provider == "elevenlabs" else None

    async def synthesize(self, text: str, language: str = "es") -> bytes:
        """Texto → audio μ-law 8kHz listo para Twilio."""
        if not text.strip():
            return b""

        # Azure Speech (output directo μ-law 8kHz, sin conversión)
        if self._provider == "azure" and self._azure:
            try:
                return await self._azure.synthesize(text, language)
            except Exception as e:
                logger.warning(f"Azure Speech falló ({e}), usando OpenAI TTS.")

        # ElevenLabs
        if self._provider == "elevenlabs" and self._elevenlabs:
            try:
                mp3 = await self._elevenlabs.synthesize(text, language)
                return _mp3_to_mulaw(mp3)
            except Exception as e:
                logger.warning(f"ElevenLabs falló ({e}), usando OpenAI TTS.")

        # OpenAI TTS (primario por defecto o fallback)
        try:
            pcm_24k = await self._openai.synthesize(text, language)
            return _pcm24k_to_mulaw8k(pcm_24k)
        except Exception as e:
            logger.error(f"OpenAI TTS falló: {e}. Devolviendo silencio.")
            return _generate_silence_mulaw(ms=500)

    async def synthesize_filler(self, language: str = "es") -> bytes:
        """Relleno de voz mientras el pipeline RAG/LLM procesa."""
        filler = random.choice(FILLER_TEXTS.get(language, FILLER_TEXTS["es"]))
        return await self.synthesize(filler, language)

    @staticmethod
    def audio_to_base64_mulaw(mulaw_bytes: bytes) -> str:
        return base64.b64encode(mulaw_bytes).decode("utf-8")


# ── Providers ─────────────────────────────────────────────────────────────────

class OpenAITTS:
    """
    OpenAI TTS — tts-1 (latencia ~600ms) o tts-1-hd (calidad máxima, ~1s).
    Multilingüe nativo. Voces disponibles: alloy, echo, fable, onyx, nova, shimmer.
    """

    # shimmer: femenina, profesional, consonantes nítidas → mejor en audio de teléfono 8kHz
    # nova: femenina, cálida → pierde calidez con compresión μ-law
    VOICE_MAP = {"es": "shimmer", "ca": "shimmer", "en": "shimmer"}

    def __init__(self):
        s = get_settings()
        self._api_key = s.openai_api_key
        self._model = s.openai_tts_model    # tts-1 | tts-1-hd
        self._speed = s.openai_tts_speed    # 0.9 recomendado (más claro al oído)

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    async def synthesize(self, text: str, language: str = "es") -> bytes:
        """Devuelve PCM 24kHz 16-bit signed mono (sin ffmpeg, conversión con audioop)."""
        voice = self.VOICE_MAP.get(language, "nova")
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "input": text,
                    "voice": voice,
                    "speed": self._speed,
                    "response_format": "pcm",  # PCM 24kHz 16-bit signed LE mono
                },
            )
            resp.raise_for_status()
            return resp.content


class AzureSpeechTTS:
    """
    Azure Cognitive Services Speech — mejor calidad para español telefónico.
    Voces neuronales: es-ES-ElviraNeural (IVR-grade, muy natural).
    Output directo raw-8khz-8bit-mono-mulaw → sin conversión, latencia mínima.
    Tier gratuito: 500K chars/mes. Precio: ~$15/1M chars.
    """

    VOICE_MAP = {
        "es": ("es-ES-ElviraNeural", "es-ES"),
        "ca": ("ca-ES-AlbaNeural",   "ca-ES"),
        "en": ("en-US-JennyNeural",  "en-US"),
    }

    def __init__(self):
        s = get_settings()
        self._key = s.azure_speech_key
        self._region = s.azure_speech_region

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    async def synthesize(self, text: str, language: str = "es") -> bytes:
        """Devuelve μ-law 8kHz directamente (formato nativo Twilio, sin conversión)."""
        import xml.sax.saxutils as saxutils
        voice_name, xml_lang = self.VOICE_MAP.get(language, self.VOICE_MAP["es"])
        safe_text = saxutils.escape(text)
        ssml = (
            f'<speak version="1.0" xml:lang="{xml_lang}">'
            f'<voice name="{voice_name}">{safe_text}</voice>'
            f'</speak>'
        )
        url = f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers={
                    "Ocp-Apim-Subscription-Key": self._key,
                    "Content-Type": "application/ssml+xml",
                    "X-Microsoft-OutputFormat": "raw-8khz-8bit-mono-mulaw",
                },
                content=ssml.encode("utf-8"),
            )
            resp.raise_for_status()
            return resp.content


class ElevenLabsTTS:
    """
    ElevenLabs TTS — activo solo si TTS_PROVIDER=elevenlabs en .env.
    Mayor naturalidad de voz y soporte de brand voice.
    """

    def __init__(self):
        s = get_settings()
        self._api_key = s.elevenlabs_api_key
        self._voice_id = s.elevenlabs_voice_id
        self._model_id = s.elevenlabs_model_id

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
    async def synthesize(self, text: str, language: str = "es") -> bytes:
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                headers={"xi-api-key": self._api_key, "Accept": "audio/mpeg"},
                json={
                    "text": text,
                    "model_id": self._model_id,
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.75,
                        "use_speaker_boost": True,
                    },
                },
            )
            resp.raise_for_status()
            return resp.content


# ── Conversión de audio ───────────────────────────────────────────────────────

def _pcm24k_to_mulaw8k(pcm_24k: bytes) -> bytes:
    """
    PCM 24kHz 16-bit signed LE mono (OpenAI TTS format) → μ-law 8kHz mono.
    Usa audioop puro — no requiere ffmpeg.
    """
    # 1. Downsample 24000 Hz → 8000 Hz (ratio 1:3)
    pcm_8k, _ = audioop.ratecv(pcm_24k, 2, 1, 24000, 8000, None)
    # 2. PCM linear 16-bit → G.711 μ-law
    return audioop.lin2ulaw(pcm_8k, 2)


def _mp3_to_mulaw(audio_bytes: bytes) -> bytes:
    """MP3 → μ-law 8000Hz mono. Requiere ffmpeg (para ElevenLabs)."""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
        audio = audio.set_channels(1).set_frame_rate(8000).set_sample_width(2)
        return audioop.lin2ulaw(audio.raw_data, 2)
    except Exception as e:
        logger.error(f"Error convirtiendo MP3 a μ-law: {e}")
        return _generate_silence_mulaw(ms=500)  # silencio en vez de ruido


def _generate_silence_mulaw(ms: int = 500) -> bytes:
    """Silencio μ-law — evita corte brusco de llamada en caso de error TTS."""
    # PCM silence (bytes cero) → convertir con audioop para obtener valor correcto
    silent_pcm = bytes(int(8000 * ms / 1000) * 2)
    return audioop.lin2ulaw(silent_pcm, 2)
