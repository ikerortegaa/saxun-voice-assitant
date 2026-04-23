"""
chat_test.py — Simula conversación con Laura sin teléfono ni Twilio.

Uso:
    python chat_test.py

Requiere: servidor corriendo → make dev
"""
import httpx
import sys

BASE_URL = "http://localhost:8000/api/v1/admin"
# Usa el SECRET_KEY de tu .env como token de admin
ADMIN_TOKEN = "change-me-in-production-use-32-chars-min"

HEADERS = {"x-admin-token": ADMIN_TOKEN}


def chat():
    history = []
    session_id = "test-cli-001"
    print("\n🎙  Simulador de Laura — Saxun Voice Assistant")
    print("   Escribe tu mensaje. 'salir' para terminar.\n")

    while True:
        try:
            user_input = input("Tú: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nSesión terminada.")
            break

        if user_input.lower() in ("salir", "exit", "quit"):
            break
        if not user_input:
            continue

        try:
            resp = httpx.post(
                f"{BASE_URL}/chat",
                headers=HEADERS,
                json={
                    "message": user_input,
                    "session_id": session_id,
                    "language": "es",
                    "history": history,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.ConnectError:
            print("❌ Servidor no responde. Ejecuta 'make dev' primero.\n")
            sys.exit(1)
        except httpx.HTTPStatusError as e:
            print(f"❌ Error HTTP {e.response.status_code}: {e.response.text}\n")
            continue

        action = data["action"]
        confidence = data["confidence"]
        chunks = data["chunks_retrieved"]

        print(f"\nLaura: {data['response']}")
        print(f"  [{action} | confianza: {confidence} | chunks: {chunks}]")

        if action == "handoff":
            print(f"  ⚠️  Derivando al agente humano: {data.get('handoff_reason')}\n")
            break

        history = data["history"]
        print()


if __name__ == "__main__":
    chat()
