"""
Contract tests — Twilio webhook endpoints.
Tests HTTP contract with Twilio without requiring real Twilio credentials.

Run: pytest src/tests/test_voice_routes.py -v
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from xml.etree import ElementTree as ET


@pytest.fixture(scope="module")
def client():
    """Minimal app with voice router only — no lifespan DB/Redis init."""
    from src.api.routes import voice_router
    app = FastAPI()
    app.include_router(voice_router, prefix="/api/v1/voice")
    return TestClient(app)


# ── POST /incoming ────────────────────────────────────────────────────────────

class TestIncomingCallWebhook:

    def test_returns_200(self, client):
        response = client.post(
            "/api/v1/voice/incoming",
            data={"CallSid": "CA123", "From": "+34600000000", "To": "+34900000000"},
        )
        assert response.status_code == 200

    def test_content_type_is_xml(self, client):
        response = client.post(
            "/api/v1/voice/incoming",
            data={"CallSid": "CA123", "From": "+34600000000", "To": "+34900000000"},
        )
        assert "xml" in response.headers["content-type"]

    def test_returns_valid_twiml_response_element(self, client):
        response = client.post(
            "/api/v1/voice/incoming",
            data={"CallSid": "CA123", "From": "+34600000000", "To": "+34900000000"},
        )
        root = ET.fromstring(response.text)
        assert root.tag == "Response"

    def test_twiml_has_connect_stream(self, client):
        response = client.post(
            "/api/v1/voice/incoming",
            data={"CallSid": "CA123", "From": "+34600000000", "To": "+34900000000"},
        )
        root = ET.fromstring(response.text)
        connect = root.find("Connect")
        assert connect is not None, "TwiML must have <Connect>"
        stream = connect.find("Stream")
        assert stream is not None, "TwiML must have <Connect><Stream>"

    def test_stream_url_uses_websocket_scheme(self, client):
        response = client.post(
            "/api/v1/voice/incoming",
            data={"CallSid": "CA123", "From": "+34600000000", "To": "+34900000000"},
        )
        root = ET.fromstring(response.text)
        url = root.find(".//Stream").get("url")
        assert url.startswith("wss://") or url.startswith("ws://")

    def test_stream_url_contains_stream_path(self, client):
        response = client.post(
            "/api/v1/voice/incoming",
            data={"CallSid": "CA123", "From": "+34600000000", "To": "+34900000000"},
        )
        root = ET.fromstring(response.text)
        url = root.find(".//Stream").get("url")
        assert "/voice/stream" in url

    def test_call_sid_passed_as_stream_parameter(self, client):
        call_sid = "CA_UNIQUE_12345"
        response = client.post(
            "/api/v1/voice/incoming",
            data={"CallSid": call_sid, "From": "+34600000000", "To": "+34900000000"},
        )
        root = ET.fromstring(response.text)
        params = root.findall(".//Parameter")
        sid_params = [p for p in params if p.get("name") == "callSid"]
        assert len(sid_params) == 1
        assert sid_params[0].get("value") == call_sid

    def test_missing_call_sid_still_returns_twiml(self, client):
        """Twilio can omit CallSid in rare cases — must not crash."""
        response = client.post(
            "/api/v1/voice/incoming",
            data={"From": "+34600000000", "To": "+34900000000"},
        )
        assert response.status_code == 200
        root = ET.fromstring(response.text)
        assert root.tag == "Response"

    def test_twiml_is_valid_xml(self, client):
        """Response must be parseable XML — Twilio rejects malformed markup."""
        response = client.post(
            "/api/v1/voice/incoming",
            data={"CallSid": "CA123", "From": "+34600000000", "To": "+34900000000"},
        )
        # ET.fromstring raises ParseError on invalid XML
        root = ET.fromstring(response.text)
        assert root is not None


# ── POST /handoff-status ──────────────────────────────────────────────────────

class TestHandoffStatusWebhook:

    def test_completed_returns_204(self, client):
        response = client.post(
            "/api/v1/voice/handoff-status",
            data={"CallSid": "CA123", "CallStatus": "completed"},
        )
        assert response.status_code == 204

    def test_in_progress_returns_204(self, client):
        response = client.post(
            "/api/v1/voice/handoff-status",
            data={"CallSid": "CA456", "CallStatus": "in-progress"},
        )
        assert response.status_code == 204

    def test_empty_body_returns_204(self, client):
        """Twilio may send partial payloads — must not crash."""
        response = client.post("/api/v1/voice/handoff-status", data={})
        assert response.status_code == 204

    def test_no_body_content(self, client):
        response = client.post(
            "/api/v1/voice/handoff-status",
            data={"CallSid": "CA789", "CallStatus": "failed"},
        )
        assert response.content == b""
