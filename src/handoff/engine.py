"""
Motor de Handoff — Orquesta la transferencia de llamada a agente humano.
Pasos: generar summary → elegir cola → transferir SIP vía Twilio → crear ticket CRM.
"""
import time
from typing import Optional

from twilio.rest import Client as TwilioClient
from loguru import logger

from src.config import get_settings
from src.models.session import Session
from src.models.handoff_models import HandoffQueue, HandoffSummary
from src.handoff.summary_generator import HandoffSummaryGenerator, QUEUE_MAP


QUEUE_NUMBERS: dict[str, str] = {}  # Se inicializa en __init__ desde settings


class HandoffEngine:
    """
    Ejecuta el handoff completo:
    1. Genera HandoffSummary (con gpt-4o-mini)
    2. Selecciona la cola correcta
    3. Transfiere la llamada vía Twilio
    4. Opcionalmente crea ticket en Zendesk
    """

    def __init__(self):
        settings = get_settings()
        self._settings = settings
        self._twilio = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
        self._summary_gen = HandoffSummaryGenerator()
        self._start_times: dict[str, float] = {}  # session_id → start_time

        # Mapeo de colas a números de teléfono/SIP
        global QUEUE_NUMBERS
        QUEUE_NUMBERS = {
            HandoffQueue.GENERAL.value:     settings.handoff_default_queue,
            HandoffQueue.TECHNICAL.value:   settings.handoff_queue_technical or settings.handoff_default_queue,
            HandoffQueue.COMMERCIAL.value:  settings.handoff_queue_commercial or settings.handoff_default_queue,
            HandoffQueue.COMPLAINTS.value:  settings.handoff_queue_complaints or settings.handoff_default_queue,
            HandoffQueue.AFTER_SALES.value: settings.handoff_default_queue,
            HandoffQueue.LOGISTICS.value:   settings.handoff_default_queue,
            HandoffQueue.DPO.value:         settings.handoff_default_queue,
            HandoffQueue.KEY_ACCOUNTS.value: settings.handoff_default_queue,
        }

    def register_call_start(self, session_id: str) -> None:
        """Registra el momento de inicio de la llamada para calcular duración."""
        self._start_times[session_id] = time.time()

    async def execute_handoff(
        self,
        session: Session,
        handoff_reason: str,
    ) -> HandoffSummary:
        """
        Ejecuta el proceso completo de handoff.
        Returns: HandoffSummary generado
        """
        start_time = self._start_times.get(session.session_id, time.time())
        duration = time.time() - start_time

        # 1. Generar summary
        logger.info(f"Iniciando handoff: session={session.session_id} reason={handoff_reason}")
        summary = await self._summary_gen.generate(session, handoff_reason, duration)

        # 2. Seleccionar número de cola
        queue_key = summary.routing_queue.value
        queue_number = QUEUE_NUMBERS.get(queue_key, self._settings.handoff_default_queue)

        if not queue_number:
            logger.error("No hay número de cola configurado para handoff")
            return summary

        # 3. Transferir llamada vía Twilio
        await self._transfer_call(session.call_sid, queue_number, summary)

        # 4. Crear ticket en CRM (si está configurado)
        if self._settings.zendesk_enabled:
            await self._create_zendesk_ticket(summary, session)

        logger.success(
            f"Handoff completado: {summary.handoff_id} → cola={queue_key} "
            f"priority={summary.priority.value}"
        )
        return summary

    def get_queue(self, handoff_reason: str) -> str:
        """Devuelve el nombre de la cola para un motivo de handoff."""
        return QUEUE_MAP.get(handoff_reason, HandoffQueue.GENERAL).value

    # ── Twilio ───────────────────────────────────────────────────────────────

    async def _transfer_call(
        self,
        call_sid: str,
        destination_number: str,
        summary: HandoffSummary,
    ) -> None:
        """Transfiere la llamada al número/SIP de agentes vía Twilio."""
        if not call_sid:
            logger.warning("No hay call_sid para transferir")
            return

        try:
            # TwiML para transferir al agente
            twiml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                "<Response>"
                f"<Dial>{destination_number}</Dial>"
                "</Response>"
            )

            self._twilio.calls(call_sid).update(
                twiml=twiml,
                status_callback=f"{self._settings.app_base_url}/api/v1/voice/handoff-status",
                status_callback_method="POST",
            )
            logger.debug(f"Twilio transfer iniciado → {destination_number}")

        except Exception as e:
            logger.error(f"Error en Twilio transfer: {e}")

    # ── CRM — Zendesk ────────────────────────────────────────────────────────

    async def _create_zendesk_ticket(
        self,
        summary: HandoffSummary,
        session: Session,
    ) -> Optional[str]:
        """Crea un ticket en Zendesk con el handoff summary."""
        if not self._settings.zendesk_enabled:
            return None

        import httpx
        import base64

        subdomain = self._settings.zendesk_subdomain
        email = self._settings.zendesk_email
        token = self._settings.zendesk_api_token

        auth = base64.b64encode(f"{email}/token:{token}".encode()).decode()
        url = f"https://{subdomain}.zendesk.com/api/v2/tickets.json"

        priority_map = {
            "inmediata": "urgent",
            "alta": "high",
            "media": "normal",
            "baja": "low",
        }

        ticket_body = {
            "ticket": {
                "subject": f"[VOZ IA] {summary.main_intent[:100]}",
                "comment": {
                    "body": summary.agent_display_text,
                },
                "priority": priority_map.get(summary.priority.value, "normal"),
                "tags": [
                    "saxun_voice_ia",
                    summary.routing_queue.value,
                    f"lang_{session.language}",
                    f"reason_{summary.handoff_reason.value}",
                ],
                "custom_fields": [
                    {"id": "session_id", "value": summary.session_id},
                    {"id": "handoff_id", "value": summary.handoff_id},
                ],
            }
        }

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    url,
                    json=ticket_body,
                    headers={
                        "Authorization": f"Basic {auth}",
                        "Content-Type": "application/json",
                    },
                )
                response.raise_for_status()
                ticket_id = response.json()["ticket"]["id"]
                logger.info(f"Ticket Zendesk creado: #{ticket_id}")
                return str(ticket_id)

        except Exception as e:
            logger.error(f"Error creando ticket Zendesk: {e}")
            return None
