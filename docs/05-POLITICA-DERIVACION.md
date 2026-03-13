# Saxun Voice Assistant — Política de Derivación a Humano
> Versión 1.0 | Fecha: 2026-03-03

---

## 1. PRINCIPIO GENERAL

> **"En caso de duda, derivar siempre."**
> El coste de una derivación innecesaria es bajo.
> El coste de una respuesta incorrecta en temas sensibles es alto.

---

## 2. TABLA MAESTRA DE REGLAS DE DERIVACIÓN

### 2.1 Derivación INMEDIATA (sin intentar responder)

| Trigger | Razón | Prioridad handoff |
|---|---|---|
| Cliente dice "queja", "reclamación formal", "denuncia" | Requiere gestor humano | ALTA |
| Cliente menciona asesoría legal / abogado / demanda | Área legal — no responder | ALTA |
| Cliente insatisfecho (tono iracundo detectado) tras >1 intento | Desescalada emocional | ALTA |
| Solicitud de datos personales del cliente (historial, contrato) | PII / GDPR | MEDIA |
| Cliente menciona accidente, daño personal o propiedad | Posible responsabilidad civil | ALTA |
| Baja/cancelación de servicio/contrato | Retención: requiere humano | MEDIA |
| Cliente pregunta por un agente humano explícitamente | Derecho del cliente | INMEDIATA |
| Consulta médica, sanitaria o de seguridad | Fuera de scope | ALTA |
| Fraude / sospecha de uso no autorizado | Seguridad | ALTA |
| Llamada de menor de edad (inferido por voz) | Protección de menores | ALTA |

### 2.2 Derivación por FALTA DE EVIDENCIA RAG

| Condición | Acción |
|---|---|
| `evidence_found = false` | Derivar tras explicar que no se tiene la info |
| `confidence < 0.65` | Derivar ofreciéndolo como alternativa |
| Pregunta sobre precios que no están en KB | Derivar a comercial |
| Pregunta sobre disponibilidad de stock en tiempo real | Derivar a comercial |
| Pregunta sobre personalización/pedido especial | Derivar a comercial |
| Pregunta sobre SLA contractual específico | Derivar a gestor de cuenta |
| Consulta técnica avanzada (instalación, configuración compleja) | Derivar a soporte técnico |

### 2.3 Derivación por LÍMITE CONVERSACIONAL

| Condición | Detalle |
|---|---|
| >3 turnos sin resolución del mismo tema | Escalación automática |
| >2 intentos de ASR fallidos consecutivos | Baja calidad de llamada |
| Llamada >8 minutos sin cierre | Escalar para eficiencia |
| Cliente ha preguntado lo mismo 2+ veces | No se está resolviendo |
| Cliente interrumpe y dice "esto no me ayuda" | Señal de insatisfacción |

### 2.4 Derivación por POLÍTICA INTERNA

| Caso | Razón |
|---|---|
| Preguntas sobre empleados concretos de Saxun | Privacidad |
| Preguntas sobre proveedores, contratos internos | Confidencial |
| Preguntas sobre situación financiera de Saxun | No pública |
| Solicitudes de auditorías o certificaciones | Proceso formal |
| Solicitudes de acceso a datos (GDPR Art. 15) | Proceso DPO |
| Solicitudes de rectificación/eliminación de datos | Proceso DPO |

---

## 3. FLUJO DE DERIVACIÓN

```
┌──────────────────────────────────────────────────────────┐
│                   FLUJO DE HANDOFF                        │
│                                                          │
│  1. TRIGGER DETECTADO                                    │
│     (LLM, guardrail, o regla explícita)                 │
│                        │                                 │
│  2. MENSAJE AL CLIENTE                                   │
│     "Le voy a pasar con un especialista ahora mismo."   │
│     (Adaptado según caso — ver scripts abajo)            │
│                        │                                 │
│  3. GENERACIÓN DE HANDOFF SUMMARY (automático)           │
│     ↓ (ver sección 4)                                   │
│                        │                                 │
│  4. ROUTING A COLA CORRECTA                             │
│     • Cola TÉCNICA                                       │
│     • Cola COMERCIAL                                     │
│     • Cola POSVENTA / GARANTÍAS                          │
│     • Cola RECLAMACIONES                                 │
│     • Cola GESTOR DE CUENTA (VIP)                        │
│                        │                                 │
│  5. TRANSFERENCIA SIP (Twilio Transfer)                  │
│     • Si no hay agentes disponibles:                    │
│       → Ofrecer callback                                │
│       → Crear ticket con prioridad                      │
│                        │                                 │
│  6. REGISTRO EN CRM                                      │
│     • Ticket auto-creado                                │
│     • Handoff summary adjunto                           │
│     • Estado: "awaiting agent"                           │
└──────────────────────────────────────────────────────────┘
```

---

## 4. HANDOFF SUMMARY (Generación Automática)

### 4.1 Estructura del summary

```json
{
  "handoff_id": "hoff_20260303_143022_abc123",
  "session_id": "sess_xyz789",
  "timestamp": "2026-03-03T14:30:22Z",
  "call_duration_seconds": 127,
  "handoff_reason": "reclamacion_formal",
  "priority": "alta",
  "routing_queue": "reclamaciones",

  "client_context": {
    "caller_id_hash": "sha256:...",
    "language": "es",
    "name_if_provided": "Juan",
    "contact_number_if_provided": "[REDACTED]",
    "order_number_if_provided": "8734"
  },

  "conversation_summary": {
    "main_intent": "El cliente reporta una reparación pendiente de más de 3 semanas sin seguimiento por parte de Saxun.",
    "key_facts": [
      "Producto enviado a reparación hace >3 semanas",
      "No ha recibido llamadas de seguimiento",
      "Ha llamado múltiples veces hoy sin resolución"
    ],
    "client_emotional_state": "frustrado",
    "attempts_by_assistant": 2,
    "rag_topics_covered": ["garantia", "proceso_reparacion"],
    "unresolved_questions": [
      "Estado exacto de la reparación",
      "Número de referencia de la reparación"
    ]
  },

  "agent_recommendations": [
    "Revisar estado de reparación antes de responder al cliente",
    "Ofrecer disculpa formal por falta de seguimiento",
    "Proporcionar timeline concreto o compensación"
  ],

  "rag_citations_used": [
    {
      "chunk_id": "proceso-reparacion_chunk_7",
      "doc_title": "Procedimiento de Reparaciones",
      "relevance": 0.88
    }
  ]
}
```

### 4.2 Texto para el agente (voz/pantalla)

```
TRANSFERENCIA DE SAXUN IA — 14:30

MOTIVO: Reclamación formal por reparación pendiente
PRIORIDAD: ALTA
CLIENTE: Juan (verificar datos completos)

RESUMEN:
El cliente envió un producto a reparar hace más de 3 semanas.
No ha recibido seguimiento. Ha llamado varias veces hoy sin resolución.
Estado emocional: frustrado.

DATOS CLAVE:
• Pedido/referencia: pendiente de verificar (cliente no lo tenía a mano)
• Tema: seguimiento de reparación

ACCIÓN RECOMENDADA:
1. Disculparse por la falta de seguimiento
2. Consultar sistema de reparaciones con datos del cliente
3. Dar fecha concreta de resolución o escalar a supervisor
```

---

## 5. SCRIPTS DE DERIVACIÓN POR CASO

```python
HANDOFF_SCRIPTS = {

    "no_evidence": (
        "No tengo esa información disponible en este momento. "
        "Para que le atiendan correctamente, le paso con uno de "
        "nuestros especialistas. Un momento."
    ),

    "low_confidence": (
        "Quiero asegurarme de darle la información exacta. "
        "Le voy a pasar con un compañero que puede confirmarlo. "
        "Un momento."
    ),

    "formal_complaint": (
        "Entiendo que quiere registrar una reclamación formal. "
        "Le transfiero ahora con nuestro equipo de incidencias "
        "para gestionarla correctamente. Le pido disculpas por "
        "los inconvenientes."
    ),

    "legal_topic": (
        "Para este tipo de consulta necesitará hablar directamente "
        "con nuestro departamento correspondiente. Le transfiero ahora."
    ),

    "explicit_agent_request": (
        "Por supuesto. Le paso con un agente ahora mismo."
    ),

    "frustrated_client": (
        "Entiendo su situación y lamento los inconvenientes. "
        "Le paso ahora con uno de nuestros responsables para "
        "que le atienda personalmente."
    ),

    "no_agents_available": (
        "En este momento todos nuestros agentes están ocupados. "
        "¿Le parece bien que le llamemos en los próximos 30 minutos? "
        "¿O prefiere esperar en línea?"
    ),

    "callback_confirmed": (
        "Perfecto. Le llamaremos al número desde el que llama. "
        "Un compañero nuestro le contactará en breve. "
        "Gracias por su paciencia."
    ),
}
```

---

## 6. ROUTING A COLAS

```python
QUEUE_ROUTING = {
    "reclamacion_formal":      "queue:reclamaciones",
    "soporte_tecnico":         "queue:soporte_tecnico",
    "garantia_posventa":       "queue:posventa",
    "consulta_comercial":      "queue:comercial",
    "pedidos_seguimiento":     "queue:logistica",
    "datos_personales_gdpr":   "queue:dpo",
    "gestor_cuenta_vip":       "queue:key_accounts",
    "default":                 "queue:atencion_general",
}

def route_handoff(handoff_reason: str, client_priority: str) -> str:
    queue = QUEUE_ROUTING.get(handoff_reason, QUEUE_ROUTING["default"])
    if client_priority == "vip":
        queue = "queue:key_accounts"
    return queue
```

---

## 7. CUANDO NO HAY AGENTES DISPONIBLES

```
Secuencia de fallback:
1. Ofrecer espera en cola (música + posición estimada)
2. Si espera > 3 min: ofrecer callback automático
3. Si rechazan espera → crear ticket + email/SMS de confirmación
4. Ticket con prioridad según razón de handoff

SLA de callback por prioridad:
• ALTA (reclamaciones, frustracion): <30 min
• MEDIA (consultas comerciales, garantías): <2 horas
• BAJA (informativas): <1 día hábil
```
