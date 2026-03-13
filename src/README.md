# Saxun Voice Assistant — Source Code

El código fuente se implementa en el MVP (Semanas 1-4).
Ver docs/08-MVP-PLAN.md para el backlog detallado.

## Módulos principales

- `api/` — FastAPI: endpoints WebSocket Twilio + REST admin
- `rag/` — Pipeline RAG: ingestión, chunking, embeddings, retrieval, guardrails
- `voice/` — STT (Deepgram) y TTS (ElevenLabs/Azure) handlers
- `conversation/` — State machine, context manager, intent classifier
- `handoff/` — Motor de derivación, handoff summary generator, queue routing
- `security/` — PII redaction, audit logging, injection detection
- `tests/` — Unit tests, integration tests, golden dataset
