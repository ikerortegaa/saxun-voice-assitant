# Saxun Voice Assistant — Plan MVP (2–4 Semanas)
> Versión 1.0 | Fecha: 2026-03-03

---

## RESUMEN EJECUTIVO

```
Semana 1: Fundamentos (Infraestructura + RAG Básico)
Semana 2: Core Conversacional (STT + LLM + TTS integrado)
Semana 3: Flujos Completos + Handoff + Tests
Semana 4: Hardening + Demo + Criterios de Aceptación
```

---

## SEMANA 1 — Fundamentos

### Objetivos
- Infraestructura base funcionando
- Pipeline RAG operativo con documentos de Saxun
- Búsqueda y citación funcionando

### Backlog Semana 1 (priorizado por valor)

| # | Tarea | Prioridad | Estimación | Responsable |
|---|---|---|---|---|
| S1-01 | Setup AWS ECS + RDS PostgreSQL + pgvector | P0 | 0.5d | DevOps |
| S1-02 | Setup Redis (sesiones) | P0 | 0.25d | DevOps |
| S1-03 | Integración Twilio (número DID + media streams) | P0 | 1d | Backend |
| S1-04 | Parser de documentos (PDF/DOCX/HTML) | P0 | 1d | Backend |
| S1-05 | Pipeline de chunking semántico | P0 | 1d | ML |
| S1-06 | Embeddings text-embedding-3-large + upsert pgvector | P0 | 0.5d | ML |
| S1-07 | Hybrid search básico (dense + BM25) | P1 | 1d | ML |
| S1-08 | Ingestión de primeros documentos Saxun | P0 | 0.5d | ML |
| S1-09 | API de retrieval con FastAPI | P0 | 0.5d | Backend |
| S1-10 | Prueba de retrieval manual (Jupyter notebook) | P0 | 0.5d | ML |
| S1-11 | Setup Langfuse (observabilidad LLM) | P1 | 0.25d | DevOps |
| S1-12 | Control de versiones de documentos (registry) | P1 | 0.5d | Backend |

### Hito Semana 1
✅ Dado un texto de consulta → el sistema devuelve los 5 chunks más relevantes con score y metadata correctos.

---

## SEMANA 2 — Core Conversacional

### Objetivos
- Pipeline completo voz: STT → RAG → LLM → TTS
- Respuestas naturales sin alucinaciones verificadas
- Conversación básica funcionando

### Backlog Semana 2

| # | Tarea | Prioridad | Estimación | Responsable |
|---|---|---|---|---|
| S2-01 | Integración Deepgram STT (streaming WebSocket) | P0 | 1d | Backend |
| S2-02 | VAD + endpointing (detección fin de turno) | P0 | 0.5d | Backend |
| S2-03 | Sistema de gestión de sesiones (Redis) | P0 | 0.5d | Backend |
| S2-04 | System prompt base (política Saxun + anti-alucinación) | P0 | 1d | ML/PM |
| S2-05 | Integración Claude Sonnet 4.6 + structured output | P0 | 0.5d | ML |
| S2-06 | Routing Haiku (simple) → Sonnet (complejo) | P1 | 0.5d | ML |
| S2-07 | Integración ElevenLabs TTS (streaming) | P0 | 1d | Backend |
| S2-08 | Pipeline E2E: audio → texto → RAG → LLM → audio | P0 | 1d | Full |
| S2-09 | Guardrails básicos (confianza, PII redaction) | P0 | 1d | ML |
| S2-10 | State machine conversacional (saludo → intent → respuesta) | P1 | 1d | Backend |
| S2-11 | Tests unitarios RAG (golden dataset v1, 20 casos) | P1 | 0.5d | QA |
| S2-12 | Barge-in detection básico | P1 | 0.5d | Backend |

### Hito Semana 2
✅ Llamada telefónica end-to-end: cliente llama → asistente contesta → responde una pregunta simple sobre Saxun con información del RAG → cliente cuelga.

---

## SEMANA 3 — Flujos Completos + Handoff + Hardening

### Objetivos
- Handoff a agente humano funcionando
- Todos los casos de uso principales cubiertos
- Suite de tests completa

### Backlog Semana 3

| # | Tarea | Prioridad | Estimación | Responsable |
|---|---|---|---|---|
| S3-01 | Motor de reglas de derivación completo | P0 | 1d | Backend/ML |
| S3-02 | Generación automática de handoff summary | P0 | 1d | ML |
| S3-03 | Integración SIP transfer (Twilio → cola agentes) | P0 | 1d | Backend |
| S3-04 | Integración CRM básica (Zendesk ticket auto) | P1 | 1d | Backend |
| S3-05 | Manejo de silencio + timeouts | P0 | 0.5d | Backend |
| S3-06 | "No te entiendo" handler + reintentos | P0 | 0.5d | Backend |
| S3-07 | Manejo de barge-in completo | P1 | 0.5d | Backend |
| S3-08 | Desambiguación de intención | P1 | 0.5d | ML |
| S3-09 | Detección de idioma + switching ES/CA/EN | P1 | 1d | ML |
| S3-10 | Tests de integración E2E (8 escenarios del doc-04) | P0 | 1d | QA |
| S3-11 | Tests adversarios (prompt injection, jailbreak) | P0 | 0.5d | QA |
| S3-12 | PII redaction end-to-end + audit logs | P0 | 0.5d | Backend |
| S3-13 | Dashboard Grafana básico (latencia, containment, WER) | P1 | 0.5d | DevOps |
| S3-14 | Alertas: Grafana → Slack | P1 | 0.25d | DevOps |

### Hito Semana 3
✅ Los 8 diálogos de ejemplo del documento 04 funcionan correctamente end-to-end. Handoff transfiere llamada a número de test de agente. Tests E2E pasan al 90%.

---

## SEMANA 4 — Demo, Hardening y Criterios de Aceptación

### Objetivos
- Sistema production-ready (no necesariamente en producción)
- Demo funcional con Saxun
- Documentación operativa

### Backlog Semana 4

| # | Tarea | Prioridad | Estimación | Responsable |
|---|---|---|---|---|
| S4-01 | Load testing (100 llamadas simultáneas simuladas) | P0 | 1d | QA/DevOps |
| S4-02 | Auto-scaling config ECS | P0 | 0.5d | DevOps |
| S4-03 | Fallback TTS (Azure si ElevenLabs falla) | P1 | 0.5d | Backend |
| S4-04 | Fallback STT (Google si Deepgram falla) | P1 | 0.5d | Backend |
| S4-05 | Health checks + circuit breakers | P0 | 0.5d | Backend |
| S4-06 | Proceso de actualización de documentos (runbook) | P0 | 0.5d | ML/DevOps |
| S4-07 | Golden dataset ampliado (50+ casos) + eval automática | P0 | 1d | ML/QA |
| S4-08 | Guía operativa para equipo Saxun | P1 | 0.5d | PM |
| S4-09 | Demo con stakeholders de Saxun | P0 | 0.5d | PM |
| S4-10 | Revisión de compliance GDPR con DPO | P0 | 0.5d | PM/Legal |
| S4-11 | Documentación API + playbook de incidentes | P1 | 0.5d | Backend |
| S4-12 | Re-ranking (cross-encoder) si tiempo permite | P2 | 1d | ML |

### Hito Semana 4
✅ Demo aprobada por Saxun. Todos los criterios de aceptación cumplidos.

---

## CRITERIOS DE ACEPTACIÓN DEL MVP

### Funcionales (MUST HAVE)
- [ ] El asistente contesta llamadas en < 3 segundos desde el primer ring
- [ ] Responde correctamente (según golden dataset) al ≥ 80% de consultas con evidencia en RAG
- [ ] NO inventa datos en ningún escenario del golden dataset (0 alucinaciones detectadas)
- [ ] Detecta y deriva reclamaciones formales en < 2 turnos
- [ ] Deriva cuando `confidence < 0.65` o `evidence_found = false`
- [ ] El handoff summary contiene los campos obligatorios en todas las derivaciones
- [ ] PII no aparece en logs (verificado en 100 transcripciones de test)
- [ ] Funciona en español (es-ES) y detecta catalán/valenciano

### No Funcionales (MUST HAVE)
- [ ] Latencia E2E < 2.5s (percentil 95)
- [ ] Disponibilidad > 99% en período de prueba
- [ ] Soporta 20 llamadas simultáneas sin degradación
- [ ] Tests unitarios coverage > 70%
- [ ] 0 vulnerabilidades críticas en SAST scan

### Deseables (NICE TO HAVE para MVP)
- [ ] Re-ranking con cross-encoder
- [ ] Dashboard Grafana completo
- [ ] Integración CRM (ticket automático)
- [ ] Voz branded de Saxun en ElevenLabs

---

## RIESGOS Y MITIGACIONES

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Documentos de Saxun en mal estado (OCR, formato) | Alta | Alto | Pre-análisis de docs en S1; OCR backup |
| Latencia E2E > 2.5s con todo integrado | Media | Alto | Prueba de latencia en S2; optimización paralela |
| Deepgram WER alto en español de Saxun (vocabulario técnico) | Media | Medio | Custom vocabulary Deepgram; fallback Azure |
| GDPR: Twilio retiene audio fuera de EU | Media | Alto | Validar región Twilio EU desde el inicio |
| Scope creep (Saxun pide features extra) | Alta | Medio | Change request formal para cualquier cambio |
| Documentos desactualizados o incompletos | Alta | Alto | Freshness policy + alertas desde S1 |
| ElevenLabs latencia en horas pico | Baja | Medio | Circuit breaker → Azure TTS automático |

---

## SUPUESTOS DEL PLAN

1. Saxun proporciona documentos en formato digital (no solo papel/OCR) en S1
2. Saxun tiene un número Twilio o acepta portabilidad en < 5 días
3. Existe cola de agentes en Twilio/sistema ACD para recibir transfers
4. AITIK tiene acceso a cuentas de Anthropic, Deepgram y ElevenLabs
5. Equipo: 1 ML Engineer, 1 Backend Engineer, 0.5 DevOps, 0.5 PM
