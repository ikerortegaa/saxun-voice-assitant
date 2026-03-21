"""
Odoo ERP/CRM integration — demo para Saxun.

Consulta pedidos en tiempo real y crea tickets de soporte.
Usa XML-RPC estándar de Odoo (sin dependencias extra, solo stdlib).

Flujo:
  1. Cliente menciona número de pedido → _process_turn detecta regex
  2. OdooClient.get_order_context() consulta sale.order + stock.picking
  3. Devuelve texto formateado → se inyecta como chunk RAG con score alto
  4. LLM responde con datos reales del pedido

Configuración (.env):
  ODOO_URL=https://mi-instancia.odoo.com
  ODOO_DB=mi_base_datos
  ODOO_USER=usuario@empresa.com
  ODOO_PASSWORD=clave_o_api_key
"""
import asyncio
import re
import xmlrpc.client
from functools import lru_cache
from typing import Optional

from loguru import logger

from src.config import get_settings


# Estado del pedido → texto en español
_ORDER_STATE_LABELS = {
    "draft":   "Borrador / Presupuesto",
    "sent":    "Presupuesto enviado al cliente",
    "sale":    "Pedido confirmado",
    "done":    "Completado y facturado",
    "cancel":  "Cancelado",
}

# Estado de la entrega → texto en español
_DELIVERY_STATE_LABELS = {
    "draft":     "Pendiente de asignación",
    "waiting":   "Esperando disponibilidad de stock",
    "confirmed": "Confirmado, pendiente de envío",
    "assigned":  "Preparado para enviar",
    "done":      "Entregado",
    "cancel":    "Cancelado",
}


class OdooClient:
    """
    Cliente Odoo XML-RPC.
    Una instancia por aplicación (singleton vía get_odoo_client).

    Nota: xmlrpc.client es síncrono. Todas las llamadas se ejecutan
    en un thread pool para no bloquear el event loop de FastAPI.
    """

    def __init__(self):
        s = get_settings()
        self._url = s.odoo_url.rstrip("/")
        self._db = s.odoo_db
        self._user = s.odoo_user
        self._password = s.odoo_password
        self._uid: Optional[int] = None

    # ── Autenticación ──────────────────────────────────────────────────────────

    def _authenticate(self) -> int:
        """Autentica y devuelve uid. El uid se cachea en la instancia."""
        if self._uid is not None:
            return self._uid
        common = xmlrpc.client.ServerProxy(
            f"{self._url}/xmlrpc/2/common", allow_none=True
        )
        uid = common.authenticate(self._db, self._user, self._password, {})
        if not uid:
            raise RuntimeError(
                f"Odoo: autenticación fallida para '{self._user}' en db '{self._db}'"
            )
        self._uid = uid
        logger.info(f"Odoo: autenticado — uid={uid}, db={self._db}")
        return uid

    def _execute_sync(self, model: str, method: str, domain: list, **kwargs):
        """Llamada síncrona a xmlrpc execute_kw."""
        uid = self._authenticate()
        models = xmlrpc.client.ServerProxy(
            f"{self._url}/xmlrpc/2/object", allow_none=True
        )
        return models.execute_kw(
            self._db, uid, self._password,
            model, method,
            [domain],
            kwargs,
        )

    async def _execute(self, model: str, method: str, domain: list, **kwargs):
        """Versión async: ejecuta _execute_sync en thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._execute_sync(model, method, domain, **kwargs),
        )

    # ── API pública ────────────────────────────────────────────────────────────

    async def get_order_context(self, order_ref: str) -> Optional[str]:
        """
        Consulta el pedido y devuelve un bloque de texto listo para
        inyectar como contexto RAG en el LLM.

        Estrategia de búsqueda:
          1. Nombre exacto (SO0001, S00001, ...)
          2. Número de pedido como parte del nombre (ilike)
          3. Si solo dígitos, probar prefijos comunes SO/S

        Retorna None si el pedido no se encuentra.
        """
        try:
            order = await self._find_order(order_ref)
            if not order:
                logger.debug(f"Odoo: pedido '{order_ref}' no encontrado")
                return None

            delivery_info = await self._get_delivery_info(order["id"])
            context = self._format_order_context(order, delivery_info)
            logger.info(
                f"Odoo: contexto generado para {order['name']} "
                f"(estado: {order.get('state')})"
            )
            return context

        except Exception as e:
            logger.warning(f"Odoo: error consultando pedido '{order_ref}': {e}")
            return None

    async def create_helpdesk_ticket(
        self,
        subject: str,
        description: str,
        order_name: str = "",
        partner_name: str = "",
    ) -> Optional[int]:
        """
        Crea un ticket en el módulo Helpdesk de Odoo.

        Retorna el ID del ticket creado, o None si falla (ej: módulo
        Helpdesk no instalado).
        """
        try:
            body = description
            if order_name:
                body = f"Pedido relacionado: {order_name}\n\n{description}"
            if partner_name:
                body = f"Cliente: {partner_name}\n{body}"

            vals = {"name": subject, "description": body}
            ticket_id = await self._execute("helpdesk.ticket", "create", [vals])
            logger.info(f"Odoo: ticket #{ticket_id} creado — '{subject}'")
            return ticket_id

        except Exception as e:
            logger.warning(f"Odoo: error creando ticket — {e}")
            return None

    # ── Helpers privados ───────────────────────────────────────────────────────

    async def _find_order(self, order_ref: str) -> Optional[dict]:
        """Busca el pedido por referencia usando múltiples estrategias."""
        fields = [
            "name", "state", "date_order", "amount_total", "currency_id",
            "order_line", "partner_id", "note", "id",
        ]

        # Candidatos a buscar (en orden de prioridad).
        # Cubre transcripciones STT erróneas donde "O" se transcribe como "0":
        #   "S00016" → digits="00016" → normalize a "16" → "SO0016", "SO16", ...
        #   "00016"  → digits_norm="16" → "SO0016", "S0016", ...
        candidates = [order_ref]
        upper = order_ref.upper()

        def _digit_variants(raw_digits: str) -> list[str]:
            """Genera variantes con diferente zero-padding para el mismo número."""
            n = raw_digits.lstrip("0") or "0"   # "00016" → "16", "0" si todo ceros
            return [
                raw_digits,                      # tal cual
                n.zfill(4),                      # "0016" (4 dígitos mínimo)
                n.zfill(5),                      # "00016"
                n,                               # sin padding
            ]

        if upper.isdigit():
            # Caso: "00016" → probar SO0016, SO00016, SO16, S0016, ...
            for d in _digit_variants(upper):
                candidates += [f"SO{d}", f"S{d}"]
        elif re.match(r'^S\d', upper):
            # Caso: "S00016" → extraer dígitos "00016" y reconstruir con prefijo SO
            digits = upper[1:]
            for d in _digit_variants(digits):
                candidates += [f"SO{d}", f"S{d}"]
        elif upper.startswith("SO"):
            # Caso: "SO00016" → variantes sin ceros extra
            digits = upper[2:]
            for d in _digit_variants(digits):
                candidates += [f"SO{d}", f"S{d}"]

        # Búsqueda exacta por nombre
        for candidate in candidates:
            results = await self._execute(
                "sale.order", "search_read",
                [["name", "=", candidate]],
                fields=fields, limit=1,
            )
            if results:
                return results[0]

        # Búsqueda parcial ilike con el ref original
        results = await self._execute(
            "sale.order", "search_read",
            [["name", "ilike", order_ref]],
            fields=fields, limit=1,
            order="date_order desc",
        )
        if results:
            return results[0]

        # Último recurso: ilike con solo los dígitos sin ceros iniciales
        # "00016" → "16" → encuentra "SO0016" que contiene "16"
        digits_only = re.sub(r'^[A-Z]*0*', '', upper)
        if digits_only and digits_only != upper:
            results = await self._execute(
                "sale.order", "search_read",
                [["name", "ilike", digits_only]],
                fields=fields, limit=1,
                order="date_order desc",
            )
            if results:
                return results[0]

        return None

    async def _get_delivery_info(self, sale_order_id: int) -> list[dict]:
        """Obtiene las entregas (pickings) asociadas al pedido."""
        try:
            return await self._execute(
                "stock.picking", "search_read",
                [
                    ["sale_id", "=", sale_order_id],
                    ["picking_type_code", "=", "outgoing"],
                ],
                fields=["name", "state", "scheduled_date", "date_done"],
                limit=5,
            )
        except Exception:
            return []

    async def _get_order_lines(self, line_ids: list[int]) -> list[dict]:
        """Obtiene las líneas del pedido."""
        if not line_ids:
            return []
        try:
            return await self._execute(
                "sale.order.line", "search_read",
                [["id", "in", line_ids]],
                fields=["product_id", "product_uom_qty", "price_unit", "price_subtotal"],
                limit=10,
            )
        except Exception:
            return []

    def _format_order_context(self, order: dict, deliveries: list[dict]) -> str:
        """Formatea los datos del pedido como texto contextual para el LLM."""
        state = _ORDER_STATE_LABELS.get(order.get("state", ""), order.get("state", ""))
        currency = (
            order["currency_id"][1]
            if order.get("currency_id") and isinstance(order["currency_id"], list)
            else "EUR"
        )
        partner = (
            order["partner_id"][1]
            if order.get("partner_id") and isinstance(order["partner_id"], list)
            else "No especificado"
        )
        date = str(order.get("date_order", ""))[:10] or "No disponible"
        total = order.get("amount_total", 0.0)

        lines = [
            f"PEDIDO {order['name']} — Información en tiempo real (Odoo ERP):",
            f"Estado: {state}",
            f"Cliente: {partner}",
            f"Fecha: {date}",
            f"Total: {total:.2f} {currency}",
        ]

        # Entregas
        if deliveries:
            delivery_parts = []
            for d in deliveries:
                d_state = _DELIVERY_STATE_LABELS.get(d.get("state", ""), d.get("state", ""))
                date_info = ""
                if d.get("date_done"):
                    date_info = f" — entregado el {str(d['date_done'])[:10]}"
                elif d.get("scheduled_date"):
                    date_info = f" — previsto para {str(d['scheduled_date'])[:10]}"
                delivery_parts.append(f"{d['name']}: {d_state}{date_info}")
            lines.append("Envío: " + " | ".join(delivery_parts))
        else:
            if order.get("state") in ("sale", "done"):
                lines.append("Envío: Sin información de entrega registrada")

        if order.get("note"):
            # Limitar nota a 200 chars para no contaminar el contexto
            note = str(order["note"])[:200].replace("\n", " ")
            lines.append(f"Notas del pedido: {note}")

        return "\n".join(lines)


@lru_cache(maxsize=1)
def get_odoo_client() -> OdooClient:
    """Singleton del cliente Odoo (una instancia por proceso)."""
    return OdooClient()
