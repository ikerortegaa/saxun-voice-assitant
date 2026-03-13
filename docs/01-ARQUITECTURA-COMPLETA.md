# Saxun Voice Assistant — Arquitectura Completa
> Versión 1.0 | Fecha: 2026-03-03 | Autor: AITIK Solutions

---

## 1. DIAGRAMA DE ARQUITECTURA (TEXT)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          SAXUN VOICE ASSISTANT — SISTEMA COMPLETO               │
└─────────────────────────────────────────────────────────────────────────────────┘

 CLIENTE
    │
    │ llamada telefónica
    ▼
┌───────────────────┐
│   PSTN / SIP      │  ← número de teléfono de Saxun
│  (Twilio / Vonage)│
└────────┬──────────┘
         │ WebSocket / webhook (media stream)
         ▼
┌─────────────────────────────────────────────────────┐
│              GATEWAY DE MEDIA & IVR                 │
│  ┌─────────────┐   ┌────────────────────────────┐   │
│  │ IVR básico  │   │ Session Manager             │   │
│  │ (menú opt.) │   │ - session_id               │   │
│  │             │   │ - caller_id (hash)          │   │
│  └──────┬──────┘   │ - idioma detectado          │   │
│         │          │ - timestamp, duración        │   │
│         └──────────┴────────────────┬────────────┘   │
└──────────────────────────────────── │ ───────────────┘
                                      │ audio PCM/μ-law stream
                                      ▼
┌─────────────────────────────────────────────────────┐
│                 STT — Speech-to-Text                │
│  Primary: Deepgram Nova-3 (streaming, <300ms)       │
│  Fallback: Google STT / Azure Speech                │
│  - VAD (Voice Activity Detection)                   │
│  - Barge-in detection                               │
│  - Speaker diarization (futuro)                     │
│  - Idioma: es-ES / ca-ES / en-US auto-detect        │
└──────────────────────┬──────────────────────────────┘
                       │ texto + confidence + timestamps
                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ORQUESTADOR PRINCIPAL (FastAPI + Python)                  │
│                                                                             │
│  ┌──────────────────┐  ┌───────────────────┐  ┌──────────────────────────┐ │
│  │  Context Manager │  │  Intent Classifier │  │  Guardrail Engine        │ │
│  │  - historial conv│  │  - LLM routing     │  │  - confidence threshold  │ │
│  │  - estado turno  │  │  - topic detection │  │  - PII detector          │ │
│  │  - memoria sesión│  │  - lang detection  │  │  - policy enforcer       │ │
│  └──────────────────┘  └───────────────────┘  └──────────────────────────┘ │
│                                  │                                          │
│                          ┌───────┴────────┐                                 │
│                          │  RAG PIPELINE  │                                 │
│                          │  (ver sección) │                                 │
│                          └───────┬────────┘                                 │
│                                  │ chunks + metadata + confidence           │
│                                  ▼                                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                    LLM — RESPONSE GENERATOR                           │  │
│  │  Model: claude-sonnet-4-6 (Anthropic) + claude-haiku-4-5 (fallback)  │  │
│  │  System prompt: política Saxun + instrucciones de voz                 │  │
│  │  - Respuesta limitada a evidencia RAG                                 │  │
│  │  - Citation tracking interno                                           │  │
│  │  - Anti-hallucination via structured output                           │  │
│  │  - Max tokens respuesta voz: ~80 tokens (~1-2 frases)                 │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                  │                                          │
│                  ┌───────────────┼───────────────┐                          │
│                  │               │               │                          │
│            RESPUESTA        DERIVACIÓN       ESCALACIÓN                     │
│            NORMAL           A HUMANO         TÉCNICA                        │
└──────────────────┼───────────────┼───────────────┼──────────────────────────┘
                   │               │               │
                   ▼               ▼               ▼
         ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
         │     TTS      │  │  HANDOFF     │  │  ALERTAS     │
         │ ElevenLabs / │  │  ENGINE      │  │  PagerDuty/  │
         │ Azure Neural │  │  - resumen   │  │  Slack       │
         │ (voz nat.)   │  │  - routing   │  └──────────────┘
         └──────┬───────┘  │  - cola ACD  │
                │          └──────┬───────┘
                │                 │
                └────────┬────────┘
                         ▼
               ┌──────────────────┐
               │ MEDIA GATEWAY    │
               │ audio → cliente  │ ← audio → agente humano (si handoff)
               └──────────────────┘

─────────────────────────────────────────────────────────────────────────────────
                         CAPA TRANSVERSAL DE DATOS
─────────────────────────────────────────────────────────────────────────────────

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌───────────┐
│   VECTOR DB      │  │  LOGGING &       │  │  CRM / TICKETING │  │  ANALYTICS│
│  (Pinecone /     │  │  OBSERVABILIDAD  │  │  (Zendesk /      │  │  Dashboard│
│   Weaviate /     │  │  - OpenTelemetry │  │   Salesforce)    │  │  Grafana  │
│   pgvector)      │  │  - Langfuse      │  │  - ticket auto   │  │  Metabase │
│  - embeddings    │  │  - logs cifrados │  │  - handoff rec.  │  │           │
│  - metadata      │  │  - audit trail   │  │  - historial CLI │  └───────────┘
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## 2. DESCRIPCIÓN DE CAPAS

### 2.1 Capa de Telefonía / IVR

| Componente | Función |
|---|---|
| PSTN/SIP | Terminación de llamada en número de Saxun |
| IVR básico | Menú mínimo (idioma, urgencia) antes de IA |
| Session Manager | Gestión de sesión, anonimización caller_id, timeout |

**Flujo de conexión:**
1. Cliente llama → Twilio recibe → asigna `call_sid`
2. Twilio abre WebSocket de media stream hacia el orquestador
3. Se inicia sesión con ID anónimo + timestamp
4. Audio fluye bidireccional en tiempo real

### 2.2 STT (Speech-to-Text)

- **Latencia objetivo**: < 300ms desde fin de utterance
- **VAD integrado**: detecta fin de turno, silencios, interrupciones
- **Confidence score**: si ASR confidence < 0.75, pedir confirmación
- **Redacción automática**: números de tarjeta, DNI → `[REDACTED]` antes de pasar al LLM

### 2.3 Orquestador

Componente central en **FastAPI (Python)**:
- Mantiene contexto de conversación por sesión
- Enruta entre RAG → LLM → TTS o → Handoff
- Aplica guardrails (umbrales, políticas, PII)
- Gestiona timeouts y reintentos

### 2.4 RAG Pipeline

Ver documento `02-RAG-DESIGN.md` para detalle completo.

### 2.5 LLM (Response Generator)

- **Modelo principal**: `claude-sonnet-4-6` (calidad, razonamiento)
- **Modelo rápido**: `claude-haiku-4-5` (respuestas simples, baja latencia)
- **Temperatura**: 0.2 (respuestas consistentes, no creativas)
- **Output estructurado**: JSON con `response_text`, `citations`, `confidence`, `action`

### 2.6 TTS (Text-to-Speech)

- **ElevenLabs** (voz más natural, latencia ~400ms)
- **Azure Neural TTS** (alternativa enterprise, SLA garantizado)
- Voz configurada como mujer/hombre → nombre ficticio (ej. "Soy Marta de Saxun")
- SSML para pausas, énfasis

### 2.7 Handoff Engine

- Detecta señal de derivación del LLM
- Genera handoff summary (JSON → texto para agente)
- Redirige llamada SIP a cola de agentes (ACD)
- Registra ticket en CRM con contexto completo

### 2.8 Observabilidad

- **Langfuse**: trazabilidad de cada llamada LLM (input, output, latencia, coste)
- **OpenTelemetry**: métricas de sistema (latencia E2E, error rates)
- **Grafana**: dashboard operacional
- **Logs**: cifrados, sin PII, retención configurable (default 90 días)
