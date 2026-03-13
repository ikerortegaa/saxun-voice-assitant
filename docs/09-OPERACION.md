# Saxun Voice Assistant — Operación y Monitorización
> Versión 1.0 | Fecha: 2026-03-03

---

## 1. DASHBOARD OPERACIONAL

### 1.1 Dashboard Principal (Grafana)

```
┌─────────────────────────────────────────────────────────────────┐
│              SAXUN VOICE AI — OPERATIONS CENTER                 │
│              Actualización: tiempo real (30s)                   │
├──────────────────┬──────────────────┬───────────────────────────┤
│  ESTADO SISTEMA  │  LLAMADAS HOY    │  CALIDAD                  │
│                  │                  │                           │
│  STT:    🟢 OK   │  Total:    142   │  Containment:  71%        │
│  LLM:    🟢 OK   │  Activas:    8   │  Handoff Rate: 29%        │
│  TTS:    🟢 OK   │  En cola:    2   │  Avg Latency: 1.8s        │
│  RAG DB: 🟢 OK   │  Handoffs:  41   │  ASR WER:     8.3%        │
│  Twilio: 🟢 OK   │  Abandonos:  3   │  CSAT:        4.3/5       │
├──────────────────┴──────────────────┴───────────────────────────┤
│                     LATENCIA E2E (24h)                          │
│  p50: 1.4s  │  p95: 2.2s  │  p99: 3.1s  │  Max: 4.2s          │
├─────────────────────────────────────────────────────────────────┤
│  TOP INTENCIONES (24h)              RAZONES DE HANDOFF (24h)    │
│  1. Garantía          (28%)         1. Sin evidencia    (42%)   │
│  2. Estado pedido     (19%)         2. Reclamación      (31%)   │
│  3. Horario/contacto  (15%)         3. Baja confianza   (15%)   │
│  4. Soporte técnico   (12%)         4. Solicitud explíc.(12%)   │
│  5. Devoluciones      (10%)                                     │
├─────────────────────────────────────────────────────────────────┤
│  ALERTAS ACTIVAS                                                │
│  🟡 p99 latencia sobre umbral en última hora (3.1s > 3.0s)      │
│  🟢 Sin errores de API en las últimas 6 horas                   │
│  🟢 Todos los documentos RAG vigentes                           │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Paneles adicionales

| Panel | Métricas | Frecuencia |
|---|---|---|
| RAG Quality | Precision@5, confianza promedio, docs más consultados | Cada hora |
| Cost Monitor | Coste API/llamada, proyección mensual | Diario |
| Security | Intentos de injection, PII leaks detectados | Tiempo real |
| Documents | Estado de freshness de todos los docs | Diario |
| Agent Handoffs | Quality score de handoff summaries | Por handoff |

---

## 2. SISTEMA DE ALERTAS

### 2.1 Alertas por severidad

```yaml
# grafana/alerts.yaml

alerts:
  - name: "Latencia E2E crítica"
    condition: "p95_latency > 3.0s durante 5 min"
    severity: CRITICAL
    channels: [pagerduty, slack-ops]
    action: "Investigar cuellos de botella; activar modo haiku-only si necesario"

  - name: "Tasa de error STT alta"
    condition: "stt_error_rate > 5% durante 10 min"
    severity: HIGH
    channels: [slack-ops]
    action: "Activar fallback Azure STT automáticamente"

  - name: "Tasa de alucinaciones detectada"
    condition: "hallucination_rate > 2% en última hora"
    severity: HIGH
    channels: [slack-ops, slack-ml]
    action: "Revisar últimas respuestas en Langfuse; pausar si > 5%"

  - name: "API Anthropic degradada"
    condition: "anthropic_error_rate > 10% durante 3 min"
    severity: CRITICAL
    channels: [pagerduty, slack-ops]
    action: "Activar modo solo-derivación; notificar a Saxun"

  - name: "Documento RAG próximo a expirar"
    condition: "doc_days_to_expiry < 5"
    severity: WARNING
    channels: [slack-content]
    action: "Notificar responsable de contenido Saxun"

  - name: "Documento RAG expirado"
    condition: "doc_expired = true"
    severity: HIGH
    channels: [slack-ops, slack-content]
    action: "Documento ya excluido de retrieval; actualizar urgente"

  - name: "Tasa de abandono alta"
    condition: "abandonment_rate > 15% en 1 hora"
    severity: MEDIUM
    channels: [slack-ops]
    action: "Revisar calidad de respuestas y tiempos de espera"
```

### 2.2 Modo de emergencia (solo-derivación)

```python
# En caso de fallo crítico del LLM o RAG:
EMERGENCY_MODE_RESPONSE = (
    "Disculpe, estamos experimentando problemas técnicos en este momento. "
    "Le paso con uno de nuestros agentes para atenderle correctamente."
)

def check_emergency_mode(metrics: SystemMetrics) -> bool:
    return (
        metrics.llm_error_rate > 0.20 or
        metrics.rag_error_rate > 0.20 or
        metrics.avg_latency > 5.0 or
        MANUAL_EMERGENCY_FLAG  # toggle manual desde dashboard
    )
```

---

## 3. PROCESO DE ACTUALIZACIÓN DE DOCUMENTOS

### 3.1 Proceso estándar (nuevo documento o actualización)

```
RESPONSABLE SAXUN (Gestor de Contenido)
              │
              │ 1. Sube nuevo documento a carpeta designada
              │    (S3/SharePoint/Drive según acuerdo)
              │
              ▼
         SISTEMA DE INGESTA (automático)
              │
              │ 2. Detecta nuevo archivo (S3 event / webhook)
              │ 3. Valida formato (PDF/DOCX/HTML)
              │ 4. Extrae texto y chunking
              │ 5. Detecta si es versión nueva de doc existente
              │    - SI: marca versión anterior como "superseded"
              │    - NO: crea nueva entrada en registry
              │ 6. Genera embeddings
              │ 7. Upsert en Vector DB
              │ 8. Verifica deduplicación
              │ 9. Notifica éxito vía Slack/email
              │
              ▼
         VALIDACIÓN (ML Engineer, 10-15 min)
              │
              │ 10. Ejecuta golden dataset eval automatizada
              │ 11. Verifica que el documento es retrievable
              │     para queries relevantes
              │ 12. Aprueba → activo en producción
```

### 3.2 Tiempos de proceso

| Tipo de cambio | Tiempo de implementación |
|---|---|
| Actualización menor (corrección de texto) | < 30 minutos |
| Nuevo documento (< 50 páginas) | < 2 horas |
| Catálogo completo (> 200 páginas) | < 4 horas |
| Cambio de política crítico (garantías, precios) | Prioritario: < 1 hora |

### 3.3 Proceso de rollback

```python
def rollback_document(doc_id: str, target_version: str):
    """Rollback a versión anterior de un documento"""

    # 1. Marcar versión actual como superseded
    db.update_document_status(doc_id, version="current", status="superseded")

    # 2. Reactivar versión anterior
    db.update_document_status(doc_id, version=target_version, status="active")

    # 3. Log de auditoría
    audit_log.write({
        "action": "document_rollback",
        "doc_id": doc_id,
        "rolled_back_to": target_version,
        "timestamp": datetime.utcnow(),
        "triggered_by": current_user
    })

    # 4. Notificación
    slack.send(f"⚠️ Rollback de documento {doc_id} a versión {target_version}")
```

---

## 4. PROCESO DE FEEDBACK Y MEJORA CONTINUA

### 4.1 Fuentes de feedback

```
1. FEEDBACK AUTOMÁTICO
   • Métricas de containment y handoff
   • Confidence scores del RAG
   • Patrones de conversación (consultas no resueltas)
   • CSAT (SMS post-llamada automático)

2. FEEDBACK DE AGENTES (post-handoff)
   • Formulario rápido (30 seg): "¿El resumen era correcto?" [Sí/No/Parcial]
   • Campo libre: "¿Qué faltaba?"
   • Se correlaciona con session_id para mejorar

3. FEEDBACK DE SUPERVISORES (semanal)
   • Revisión de 10-20 transcripciones aleatorias
   • Calificación: correcto / incorrecto / podría mejorarse
   • Input para golden dataset
```

### 4.2 Ciclo de mejora mensual

```
Semana 1: Recolección y análisis de datos del mes anterior
  • Extraer consultas más frecuentes no resueltas
  • Identificar documentos con baja cobertura
  • Revisar false positivos/negativos de handoff

Semana 2: Actualización de contenido
  • Saxun sube documentos que cubren gaps identificados
  • Actualización de FAQs con nuevas preguntas reales

Semana 3: Tuning del sistema
  • Ajuste de umbrales de confianza si necesario
  • Actualización del golden dataset
  • Ajuste del system prompt si hay patrones de error

Semana 4: Validación y despliegue
  • Golden dataset eval
  • A/B test si cambios significativos
  • Deploy con feature flags (rollout gradual 10% → 50% → 100%)
```

---

## 5. GESTIÓN DE INCIDENTES

### 5.1 Niveles de severidad

| Nivel | Definición | Tiempo de respuesta | Tiempo de resolución |
|---|---|---|---|
| P0 | Sistema completamente caído / no responde llamadas | < 5 min | < 1 hora |
| P1 | Alucinaciones detectadas / PII en logs / Handoff roto | < 15 min | < 2 horas |
| P2 | Latencia alta / containment rate bajo | < 1 hora | < 4 horas |
| P3 | Documento expirado / métrica de calidad en umbral | < 4 horas | < 1 día |

### 5.2 On-call rotation

```
Semana en curso: 1 ML Engineer + 1 Backend Engineer de guardia
Horario de cobertura: 8:00 - 22:00 (horario ES)
Fuera de horario: modo emergencia activo → solo derivación automática
Escalación: Slack → PagerDuty → llamada directa
```

---

## 6. CAPACIDAD Y ESCALADO

### 6.1 Sizing para distintos volúmenes

| Volumen | Llamadas/mes | Llamadas simultáneas peak | Infra recomendada |
|---|---|---|---|
| MVP | < 5,000 | 10-20 | 2 instancias ECS, RDS t3.medium |
| Crecimiento | 5,000-25,000 | 50-100 | 4-6 instancias, RDS t3.large |
| Escala | 25,000-100,000 | 200-500 | 8-12 instancias, RDS r6g.large |
| Enterprise | > 100,000 | > 500 | Multi-region, Aurora |

### 6.2 Auto-scaling policy

```python
# ECS Auto Scaling
scaling_policy = {
    "metric": "concurrent_calls",
    "scale_out_threshold": 15,   # si hay 15 llamadas por instancia → añadir
    "scale_in_threshold": 5,     # si hay < 5 llamadas por instancia → reducir
    "min_capacity": 2,
    "max_capacity": 20,
    "cooldown_scale_out": 60,    # segundos
    "cooldown_scale_in": 300,
}
```

---

## 7. RUNBOOKS

### Runbook 1: Respuesta a latencia alta

```
SÍNTOMA: Alert "Latencia E2E > 3s"

DIAGNÓSTICO:
1. Verificar Langfuse → ¿cuál paso es el lento?
   - STT > 500ms? → revisar Deepgram status page
   - RAG > 800ms? → revisar pgvector query plan; ver EXPLAIN ANALYZE
   - LLM > 1500ms? → revisar Anthropic status; activar haiku-only
   - TTS > 600ms? → revisar ElevenLabs status; activar Azure TTS

ACCIONES:
• LLM lento → activar flag HAIKU_ONLY_MODE en Redis
• STT lento → activar fallback_stt=azure en config
• TTS lento → activar fallback_tts=azure en config
• Si todo lento → activar EMERGENCY_MODE (solo derivación)

RECUPERACIÓN:
• Cuando servicio externo se recupere → desactivar flags de fallback
• Verificar que latencia vuelve a < 2.5s p95
• Cerrar alerta + post-mortem si duró > 30 min
```

### Runbook 2: Actualización urgente de documento

```
TRIGGER: Saxun comunica que un precio/política ha cambiado y debe
          actualizarse inmediatamente

1. Saxun sube nuevo documento al bucket S3 designado
2. ML Engineer ejecuta: python scripts/ingest_single.py [ruta_doc]
3. Verificar en logs: "ingested N chunks, superseded M old chunks"
4. Ejecutar: python scripts/verify_retrieval.py --query "[consulta de prueba]"
5. Verificar que el nuevo contenido aparece en top-3 resultados
6. Confirmar a Saxun: "Actualización completada a las HH:MM"
Tiempo objetivo: < 30 minutos
```
