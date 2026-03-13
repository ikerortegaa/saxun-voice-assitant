# Saxun Voice Assistant — Índice de Documentación
> AITIK Solutions | Versión 1.0 | Fecha: 2026-03-03

---

## DOCUMENTOS DEL PROYECTO

| # | Documento | Descripción |
|---|---|---|
| 01 | [Arquitectura Completa](01-ARQUITECTURA-COMPLETA.md) | Diagrama E2E, descripción de capas, componentes |
| 02 | [Stack Recomendado](02-STACK-RECOMENDADO.md) | Tecnologías, pros/contras, costes estimados |
| 03 | [Diseño RAG](03-RAG-DESIGN.md) | Ingestión, chunking, retrieval, guardrails, freshness |
| 04 | [Flujo Conversacional](04-FLUJO-CONVERSACIONAL.md) | State machine, diálogos de ejemplo, manejo de casos de voz |
| 05 | [Política de Derivación](05-POLITICA-DERIVACION.md) | Reglas de handoff, handoff summary, routing a colas |
| 06 | [Seguridad y Compliance](06-SEGURIDAD-COMPLIANCE.md) | GDPR, PII, cifrado, audit trail, prompt injection |
| 07 | [Plan de Pruebas](07-PLAN-PRUEBAS.md) | Unit tests, E2E tests, adversarios, métricas KPI |
| 08 | [Plan MVP (2–4 semanas)](08-MVP-PLAN.md) | Backlog priorizado, hitos, riesgos, criterios de aceptación |
| 09 | [Operación](09-OPERACION.md) | Monitorización, alertas, actualización de docs, runbooks |
| 10 | [Preguntas Críticas](10-PREGUNTAS-CRITICAS.md) | Preguntas para Saxun + supuestos razonables |

---

## ESTRUCTURA DEL PROYECTO

```
saxun-voice-assistant/
├── docs/                    ← Documentación de arquitectura (este directorio)
├── rag-docs/                ← Documentos corporativos de Saxun (a rellenar)
│   ├── productos/
│   ├── politicas/
│   ├── soporte/
│   ├── comercial/
│   └── _meta/
└── src/                     ← Código fuente (a implementar en MVP)
    ├── api/                 ← FastAPI — endpoints del orquestador
    ├── rag/                 ← Pipeline RAG (ingestión, retrieval, guardrails)
    ├── voice/               ← STT y TTS handlers
    ├── conversation/        ← State machine y gestión de sesiones
    ├── handoff/             ← Motor de derivación y handoff summary
    ├── security/            ← PII redaction, guardrails, audit logging
    └── tests/               ← Tests unitarios e integración
```

---

## RESUMEN EJECUTIVO

### ¿Qué construimos?
Un asistente de voz IA para el contact center de Saxun que:
1. **Contesta llamadas** de forma natural (como una persona)
2. **Responde con fiabilidad** basándose en documentos corporativos (RAG)
3. **Nunca inventa** información; si no sabe, lo dice
4. **Deriva a humanos** cuando es necesario, con un resumen automático
5. **Cumple GDPR** y protege datos de clientes

### Coste estimado (MVP, 5,000 llamadas/mes)
- Infraestructura: ~€377/mes
- Personal de operación: ~0.5 FTE/mes
- **Total servicio recurrente recomendado**: €1,500-2,500/mes (incluyendo soporte y mejoras)

### Timeline
- **Semana 1**: RAG + infra base
- **Semana 2**: Pipeline de voz E2E
- **Semana 3**: Handoff + tests + multiidioma
- **Semana 4**: Hardening + demo con Saxun

### Stack Principal
```
Telefonía: Twilio | STT: Deepgram Nova-3 | LLM: Claude Sonnet 4.6
RAG: pgvector + LangChain | TTS: ElevenLabs | Observabilidad: Langfuse + Grafana
Infra: AWS ECS Fargate (EU-West-1) | Compliance: GDPR EU
```
