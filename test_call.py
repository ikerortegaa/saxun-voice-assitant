"""
test_call.py — Lanza una llamada de prueba desde Twilio a tu número.

Uso:
    python test_call.py +34XXXXXXXXX

Cómo funciona:
  Twilio llama a TU número → cuando lo coges, conecta con el bot.
  No pagas nada en tu compañia. Twilio cobra ~€0.02/min desde la cuenta.
"""
import sys
import os
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
BASE_URL    = os.getenv("APP_BASE_URL")

def call(to: str) -> None:
    if not all([ACCOUNT_SID, AUTH_TOKEN, FROM_NUMBER, BASE_URL]):
        print("❌ Faltan variables en .env (TWILIO_ACCOUNT_SID / AUTH_TOKEN / PHONE_NUMBER / APP_BASE_URL)")
        sys.exit(1)

    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    call = client.calls.create(
        to=to,
        from_=FROM_NUMBER,
        url=f"{BASE_URL}/api/v1/voice/incoming",   # mismo webhook que las llamadas entrantes
        method="POST",
    )

    print(f"✅ Llamada iniciada → {to}")
    print(f"   SID: {call.sid}")
    print(f"   Estado: {call.status}")
    print(f"\n   Coge el teléfono. Twilio te llama ahora.")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python test_call.py +34XXXXXXXXX")
        sys.exit(1)
    call(sys.argv[1])
