"""
Rutas de voz — Integración con Twilio Media Streams.

Flujo:
1. POST /incoming  → Twilio llama al webhook cuando llega una llamada
                     Responde con TwiML para abrir Media Stream WebSocket
2. WS  /stream     → Twilio abre WebSocket bidireccional de audio
                     Aquí vive el pipeline STT → RAG → LLM → TTS
3. POST /handoff-status → Twilio notifica eventos de transferencia
"""
import asyncio
import base64
import json
import time

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from loguru import logger

from src.config import get_settings
from src.db.database import get_db_pool, get_redis
from src.conversation.context_manager import SessionContextManager
from src.conversation.state_machine import ConversationOrchestrator
from src.rag.retriever import HybridRetriever
from src.voice.stt import DeepgramSTT, LanguageDetector
from src.voice.tts import TTSService
from src.handoff.engine import HandoffEngine

router = APIRouter()


# ── 1. Webhook entrada de llamada (TwiML) ────────────────────────────────────

@router.post("/incoming")
async def incoming_call(request: Request):
    """
    Twilio llama a este endpoint cuando llega una llamada.
    Responde con TwiML que abre un Media Stream WebSocket hacia /stream.
    """
    form_data = await request.form()
    call_sid = form_data.get("CallSid", "")
    from_number = form_data.get("From", "anonymous")
    to_number = form_data.get("To", "")

    logger.info(f"Llamada entrante: CallSid={call_sid} From=REDACTED To={to_number}")

    settings = get_settings()
    ws_url = settings.app_base_url.replace("https://", "wss://").replace("http://", "ws://")
    stream_url = f"{ws_url}/api/v1/voice/stream"

    # TwiML: abrir Media Stream + mensaje inicial de espera
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="{stream_url}">
            <Parameter name="callSid" value="{call_sid}" />
            <Parameter name="fromNumber" value="{from_number}" />
        </Stream>
    </Connect>
</Response>"""

    return Response(content=twiml, media_type="application/xml")


# ── 2. WebSocket de Media Stream ─────────────────────────────────────────────

@router.websocket("/stream")
async def media_stream(websocket: WebSocket):
    """
    WebSocket bidireccional con Twilio Media Streams.
    Protocolo: JSON messages con eventos (connected, start, media, stop).
    Audio: base64 encoded μ-law 8000Hz.
    """
    await websocket.accept()

    db_pool = await get_db_pool()
    redis = await get_redis()

    settings = get_settings()
    ctx_manager = SessionContextManager(redis)
    retriever = HybridRetriever(db_pool)
    tts = TTSService()
    handoff_engine = HandoffEngine()
    lang_detector = LanguageDetector()

    session = None
    orchestrator: ConversationOrchestrator | None = None
    stt: DeepgramSTT | None = None
    stream_sid = ""
    call_sid = ""
    from_number = "anonymous"
    silence_task = None
    last_audio_time = time.time()

    # Lock para envío de audio (evitar overlapping)
    send_lock = asyncio.Lock()

    async def send_audio_to_twilio(audio_bytes: bytes) -> None:
        """Envía audio μ-law al cliente vía Twilio WebSocket."""
        if not audio_bytes:
            return
        async with send_lock:
            payload = base64.b64encode(audio_bytes).decode("utf-8")
            message = json.dumps({
                "event": "media",
                "streamSid": stream_sid,
                "media": {"payload": payload},
            })
            try:
                await websocket.send_text(message)
            except Exception as e:
                logger.warning(f"Error enviando audio a Twilio: {e}")

    def on_transcript(result) -> None:
        """Callback STT → encolar turno para procesamiento."""
        if result.is_final and result.text.strip():
            nonlocal last_audio_time
            last_audio_time = time.time()
            asyncio.create_task(
                orchestrator.on_transcript(result)
            )

    try:
        async for raw_message in websocket.iter_text():
            message = json.loads(raw_message)
            event = message.get("event", "")

            # ── Evento: connected (handshake inicial) ────────────────────────
            if event == "connected":
                logger.debug("Twilio WebSocket: connected")

            # ── Evento: start (información de la llamada) ────────────────────
            elif event == "start":
                start_data = message.get("start", {})
                stream_sid = message.get("streamSid", "")
                call_sid = start_data.get("callSid", "")
                custom_params = start_data.get("customParameters", {})
                from_number = custom_params.get("fromNumber", "anonymous")

                logger.info(f"Stream iniciado: streamSid={stream_sid} callSid={call_sid}")

                # Crear sesión
                session = await ctx_manager.create_session(
                    call_sid=call_sid,
                    caller_number=from_number,
                    stream_sid=stream_sid,
                )

                # Inicializar STT
                stt = DeepgramSTT(
                    on_transcript=on_transcript,
                    language=session.language,
                )
                await stt.connect()

                # Inicializar orquestador
                orchestrator = ConversationOrchestrator(
                    session=session,
                    retriever=retriever,
                    tts=tts,
                    context_manager=ctx_manager,
                    send_audio_fn=send_audio_to_twilio,
                    handoff_engine=handoff_engine,
                )
                handoff_engine.register_call_start(session.session_id)

                # Saludo inicial
                await orchestrator.on_call_start()

                # Iniciar monitor de silencio
                silence_task = asyncio.create_task(
                    _silence_monitor(orchestrator, lambda: last_audio_time)
                )

            # ── Evento: media (chunk de audio del cliente) ───────────────────
            elif event == "media":
                if stt and stt.is_connected:
                    payload = message.get("media", {}).get("payload", "")
                    if payload:
                        last_audio_time = time.time()
                        await stt.send_audio(payload)

            # ── Evento: stop (llamada terminada) ─────────────────────────────
            elif event == "stop":
                logger.info(f"Stream terminado: {stream_sid}")
                break

    except WebSocketDisconnect:
        logger.info(f"WebSocket desconectado: {stream_sid}")
    except Exception as e:
        logger.exception(f"Error en Media Stream: {e}")
    finally:
        # Cleanup
        if silence_task:
            silence_task.cancel()
        if stt:
            await stt.disconnect()
        if orchestrator and session:
            await orchestrator.on_call_end(reason="disconnect")


async def _silence_monitor(
    orchestrator: ConversationOrchestrator,
    get_last_audio: callable,
    check_interval: float = 1.0,
) -> None:
    """Tarea en background: detecta silencios y notifica al orquestador."""
    try:
        while True:
            await asyncio.sleep(check_interval)
            silence_duration = time.time() - get_last_audio()
            if silence_duration >= 3.0:
                await orchestrator.on_silence(silence_duration)
    except asyncio.CancelledError:
        pass


# ── 3. Status callback de handoff ────────────────────────────────────────────

@router.post("/handoff-status")
async def handoff_status(request: Request):
    """
    Twilio notifica aquí el estado de la transferencia de llamada.
    Útil para logging y métricas.
    """
    form_data = await request.form()
    call_status = form_data.get("CallStatus", "")
    call_sid = form_data.get("CallSid", "")
    logger.info(f"Handoff status: CallSid={call_sid} Status={call_status}")
    return Response(content="", status_code=204)
