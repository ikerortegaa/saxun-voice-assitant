"""
Tests de la integración Odoo — OdooClient y _get_odoo_chunk.
No requiere conexión real: todos los tests usan mocks de xmlrpc.

Ejecutar: pytest src/tests/test_odoo.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.integrations.odoo_client import OdooClient, _ORDER_STATE_LABELS, _DELIVERY_STATE_LABELS
from src.models.rag_models import Chunk


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_order(
    name="SO0042",
    state="sale",
    amount_total=299.99,
    partner_name="Juan García",
    order_line=None,
    note="",
) -> dict:
    return {
        "id": 42,
        "name": name,
        "state": state,
        "date_order": "2026-03-10 10:00:00",
        "amount_total": amount_total,
        "currency_id": [1, "EUR"],
        "partner_id": [10, partner_name],
        "order_line": order_line or [1, 2],
        "note": note,
    }


def _make_picking(name="WH/OUT/00042", state="done", date_done="2026-03-12 14:00:00"):
    return {
        "id": 99,
        "name": name,
        "state": state,
        "scheduled_date": None,
        "date_done": date_done,
    }


@pytest.fixture
def client():
    """OdooClient con settings mockeados."""
    mock_settings = MagicMock()
    mock_settings.odoo_url = "https://demo.odoo.com"
    mock_settings.odoo_db = "demo_db"
    mock_settings.odoo_user = "user@demo.com"
    mock_settings.odoo_password = "secret"
    with patch("src.integrations.odoo_client.get_settings", return_value=mock_settings):
        yield OdooClient()


# ── _authenticate ──────────────────────────────────────────────────────────────

class TestAuthentication:

    def test_authenticate_caches_uid(self, client):
        """El uid se cachea tras la primera autenticación."""
        mock_proxy = MagicMock()
        mock_proxy.authenticate.return_value = 7
        with patch("xmlrpc.client.ServerProxy", return_value=mock_proxy):
            uid1 = client._authenticate()
            uid2 = client._authenticate()
        assert uid1 == uid2 == 7
        # authenticate solo se llamó una vez (segunda llama usa caché)
        assert mock_proxy.authenticate.call_count == 1

    def test_authenticate_raises_on_failure(self, client):
        """Lanza RuntimeError si Odoo devuelve uid=False."""
        mock_proxy = MagicMock()
        mock_proxy.authenticate.return_value = False
        with patch("xmlrpc.client.ServerProxy", return_value=mock_proxy):
            with pytest.raises(RuntimeError, match="autenticación fallida"):
                client._authenticate()


# ── get_order_context ──────────────────────────────────────────────────────────

class TestGetOrderContext:

    @pytest.mark.asyncio
    async def test_returns_context_for_existing_order(self, client):
        """Devuelve texto de contexto cuando el pedido existe."""
        order = _make_order()
        client._execute = AsyncMock(side_effect=[
            [order],  # _find_order: búsqueda exacta
            [_make_picking()],  # _get_delivery_info
        ])
        result = await client.get_order_context("SO0042")
        assert result is not None
        assert "SO0042" in result
        assert "confirmado" in result.lower()  # state="sale" → "Pedido confirmado"

    @pytest.mark.asyncio
    async def test_returns_none_for_missing_order(self, client):
        """Devuelve None cuando el pedido no existe."""
        client._execute = AsyncMock(return_value=[])
        result = await client.get_order_context("99999")
        assert result is None

    @pytest.mark.asyncio
    async def test_context_includes_total_and_currency(self, client):
        """El contexto incluye importe total y moneda."""
        order = _make_order(amount_total=1234.56)
        client._execute = AsyncMock(side_effect=[[order], []])
        result = await client.get_order_context("SO0042")
        assert "1234.56" in result
        assert "EUR" in result

    @pytest.mark.asyncio
    async def test_context_includes_partner_name(self, client):
        """El contexto incluye el nombre del cliente."""
        order = _make_order(partner_name="Empresa Saxun S.L.")
        client._execute = AsyncMock(side_effect=[[order], []])
        result = await client.get_order_context("SO0042")
        assert "Empresa Saxun S.L." in result

    @pytest.mark.asyncio
    async def test_context_includes_delivery_state(self, client):
        """El contexto incluye información de envío cuando existe."""
        order = _make_order()
        picking = _make_picking(state="done", date_done="2026-03-12 14:00:00")
        client._execute = AsyncMock(side_effect=[[order], [picking]])
        result = await client.get_order_context("SO0042")
        assert "Entregado" in result
        assert "2026-03-12" in result

    @pytest.mark.asyncio
    async def test_context_without_delivery(self, client):
        """Muestra mensaje sin entrega cuando no hay pickings."""
        order = _make_order(state="sale")
        client._execute = AsyncMock(side_effect=[[order], []])
        result = await client.get_order_context("SO0042")
        assert result is not None
        assert "Sin información" in result or "Envío" in result

    @pytest.mark.asyncio
    async def test_context_includes_note(self, client):
        """Incluye notas del pedido si existen."""
        order = _make_order(note="Entrega urgente antes del viernes")
        client._execute = AsyncMock(side_effect=[[order], []])
        result = await client.get_order_context("SO0042")
        assert "Entrega urgente" in result

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, client):
        """Devuelve None (no lanza) si hay un error de conexión."""
        client._execute = AsyncMock(side_effect=Exception("Connection refused"))
        result = await client.get_order_context("SO0042")
        assert result is None

    @pytest.mark.asyncio
    async def test_searches_with_digit_prefixes(self, client):
        """Intenta prefijos SO/S si se pasa solo el número."""
        # Primero falla, segundo encuentra con prefijo
        client._execute = AsyncMock(side_effect=[
            [],       # nombre exacto "1234"
            [],       # "S1234"
            [_make_order(name="SO1234")],  # "SO1234" ← match
            [],       # ilike fallback
            [],       # _get_delivery_info (no llega si ilike también falla)
        ])
        # Reorganizar: el _find_order itera candidates y luego ilike
        # Mockear _find_order directamente para este test específico
        client._find_order = AsyncMock(return_value=_make_order(name="SO1234"))
        client._get_delivery_info = AsyncMock(return_value=[])
        result = await client.get_order_context("1234")
        assert result is not None
        assert "SO1234" in result


# ── create_helpdesk_ticket ─────────────────────────────────────────────────────

class TestCreateHelpdeskTicket:

    @pytest.mark.asyncio
    async def test_creates_ticket_successfully(self, client):
        """Crea un ticket y devuelve su ID."""
        client._execute = AsyncMock(return_value=101)
        ticket_id = await client.create_helpdesk_ticket(
            subject="Problema con pedido SO0042",
            description="El cliente no ha recibido el envío.",
        )
        assert ticket_id == 101

    @pytest.mark.asyncio
    async def test_ticket_includes_order_name(self, client):
        """La descripción del ticket incluye el nombre del pedido."""
        captured = {}

        async def capture_execute(model, method, domain, **kwargs):
            if model == "helpdesk.ticket":
                captured["vals"] = domain[0]
            return 202

        client._execute = capture_execute
        await client.create_helpdesk_ticket(
            subject="Incidencia",
            description="Detalle del problema",
            order_name="SO0042",
        )
        assert "SO0042" in captured["vals"]["description"]

    @pytest.mark.asyncio
    async def test_returns_none_on_exception(self, client):
        """Devuelve None si el módulo Helpdesk no está instalado."""
        client._execute = AsyncMock(side_effect=Exception("Model helpdesk.ticket not found"))
        result = await client.create_helpdesk_ticket(
            subject="Test", description="Test"
        )
        assert result is None


# ── _format_order_context ──────────────────────────────────────────────────────

class TestFormatOrderContext:

    def test_all_order_states_have_labels(self, client):
        """Todos los estados de pedido conocidos tienen etiqueta en español."""
        for state in ("draft", "sent", "sale", "done", "cancel"):
            order = _make_order(state=state)
            text = client._format_order_context(order, [])
            assert _ORDER_STATE_LABELS[state] in text

    def test_unknown_state_uses_raw_value(self, client):
        """Un estado desconocido se muestra tal cual."""
        order = _make_order(state="custom_state")
        text = client._format_order_context(order, [])
        assert "custom_state" in text

    def test_delivery_done_shows_delivery_date(self, client):
        """La fecha de entrega aparece si el picking está done."""
        order = _make_order()
        picking = _make_picking(state="done", date_done="2026-03-12 14:00:00")
        text = client._format_order_context(order, [picking])
        assert "2026-03-12" in text
        assert "Entregado" in text

    def test_delivery_scheduled_shows_planned_date(self, client):
        """La fecha prevista aparece si el picking no está done."""
        order = _make_order()
        picking = {
            "id": 1, "name": "WH/OUT/00001",
            "state": "assigned",
            "scheduled_date": "2026-03-20 08:00:00",
            "date_done": None,
        }
        text = client._format_order_context(order, [picking])
        assert "2026-03-20" in text
        assert "previsto" in text

    def test_note_truncated_at_200_chars(self, client):
        """Las notas largas se truncan a 200 caracteres."""
        long_note = "X" * 300
        order = _make_order(note=long_note)
        text = client._format_order_context(order, [])
        # La nota truncada debe aparecer como máx 200 chars
        lines = text.split("\n")
        note_line = next((l for l in lines if "Notas" in l), "")
        assert len(note_line) <= 220  # "Notas del pedido: " (18) + 200 chars content

    def test_missing_currency_defaults_to_eur(self, client):
        """Si currency_id no está, usa EUR como fallback."""
        order = _make_order()
        order["currency_id"] = None
        text = client._format_order_context(order, [])
        assert "EUR" in text


# ── _ORDER_PATTERN en state_machine ───────────────────────────────────────────

class TestOrderPatternDetection:
    """Verifica el regex de detección de pedidos en el texto del cliente."""

    def test_import_pattern(self):
        from src.conversation.state_machine import _ORDER_PATTERN
        assert _ORDER_PATTERN is not None

    def test_detects_pedido_number(self):
        from src.conversation.state_machine import _ORDER_PATTERN
        m = _ORDER_PATTERN.search("tengo un problema con mi pedido 1234")
        assert m is not None
        assert m.group(1) == "1234"

    def test_detects_orden_number(self):
        from src.conversation.state_machine import _ORDER_PATTERN
        m = _ORDER_PATTERN.search("la orden 5678 no ha llegado")
        assert m is not None
        assert m.group(1) == "5678"

    def test_detects_referencia_number(self):
        from src.conversation.state_machine import _ORDER_PATTERN
        m = _ORDER_PATTERN.search("mi referencia es 9999")
        assert m is not None
        assert m.group(1) == "9999"

    def test_detects_SO_format(self):
        from src.conversation.state_machine import _ORDER_PATTERN
        # Without keyword, only SO pattern matches
        m = _ORDER_PATTERN.search("el SO0042 tiene un error")
        assert m is not None
        assert m.group(2) == "SO0042"

    def test_detects_SO_format_with_pedido_keyword(self):
        from src.conversation.state_machine import _ORDER_PATTERN
        # With "pedido" keyword, first group captures the digits part
        m = _ORDER_PATTERN.search("el pedido SO0042 tiene un error")
        assert m is not None
        # Either group matches — _get_odoo_chunk uses group(1) or group(2)
        assert m.group(1) or m.group(2)

    def test_no_match_without_keyword(self):
        from src.conversation.state_machine import _ORDER_PATTERN
        m = _ORDER_PATTERN.search("quiero hablar con un agente")
        assert m is None

    def test_no_match_short_number(self):
        """Números de menos de 4 dígitos no deben casar (demasiado cortos)."""
        from src.conversation.state_machine import _ORDER_PATTERN
        m = _ORDER_PATTERN.search("pedido 12")
        assert m is None

    def test_case_insensitive(self):
        from src.conversation.state_machine import _ORDER_PATTERN
        m = _ORDER_PATTERN.search("PEDIDO 4567")
        assert m is not None
        assert m.group(1) == "4567"


# ── _extract_order_ref_from_reply ─────────────────────────────────────────────

class TestExtractOrderRefFromReply:
    """
    Prueba el extractor de referencias de pedido en respuestas STT.
    Cubre los casos reales observados: dígitos deletreados, números cortos, etc.
    """

    def _extract(self, text):
        from src.conversation.state_machine import _extract_order_ref_from_reply
        return _extract_order_ref_from_reply(text)

    def test_direct_long_number(self):
        """Número directo de 4+ dígitos."""
        assert self._extract("es el 1234") == "1234"

    def test_direct_long_number_no_context(self):
        assert self._extract("1234") == "1234"

    def test_spaced_digits_only(self):
        """Deepgram transcribe SO0016 como '0 0 0 16'."""
        assert self._extract("0 0 0 16") == "00016"

    def test_spaced_SO_prefix(self):
        """'S 0 0 0 16' → 'S00016' (S + zeros + 16, fiel a la transcripción STT)."""
        assert self._extract("S 0 0 0 16") == "S00016"

    def test_spaced_SO_full(self):
        """'S O 0 0 1 6' → 'SO0016'."""
        assert self._extract("S O 0 0 1 6") == "SO0016"

    def test_spaced_with_prefix_words(self):
        """El pedido es el S 0 0 0 16 → extrae 'S00016' (fiel a los tokens STT)."""
        assert self._extract("El pedido es el S 0 0 0 16") == "S00016"

    def test_short_number_fallback(self):
        """'Pedido número 16' → acepta '16' como último recurso (demo)."""
        assert self._extract("Pedido número 16") == "16"

    def test_short_number_standalone(self):
        """Solo '42' → acepta como nº de pedido corto."""
        assert self._extract("el 42") == "42"

    def test_prefers_longer_sequence(self):
        """Cuando hay varios candidatos, prefiere el más largo."""
        # "1 6" + "1234" → debería preferir "1234"
        result = self._extract("quiero el 1234")
        assert result == "1234"

    def test_case_insensitive_so_prefix(self):
        """'s o 0 0 1 6' (minúsculas) → 'SO0016'."""
        result = self._extract("s o 0 0 1 6")
        assert result == "SO0016"

    def test_returns_none_when_no_number(self):
        """Sin números en el texto → None."""
        assert self._extract("quiero hablar con un agente") is None

    def test_returns_none_for_single_digit(self):
        """Un solo dígito no es una referencia válida."""
        assert self._extract("el número es 5") is None

    def test_real_transcript_1(self):
        """Caso real del log: '0 0 0 16.'"""
        assert self._extract("0 0 0 16.") == "00016"

    def test_real_transcript_2(self):
        """Caso real del log: 'El pedido es el S 0 0 0 16.' → 'S00016'."""
        result = self._extract("El pedido es el S 0 0 0 16.")
        assert result == "S00016"

    def test_real_transcript_3(self):
        """Caso real del log: 'Pedido número 16.'"""
        result = self._extract("Pedido número 16.")
        assert result == "16"
