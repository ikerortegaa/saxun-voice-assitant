# Saxun Voice Assistant — Seguridad y Compliance
> Versión 1.0 | Fecha: 2026-03-03

---

## 1. MARCO DE COMPLIANCE

| Regulación | Aplicabilidad | Estado objetivo |
|---|---|---|
| GDPR (EU 2016/679) | Total — datos de clientes EU | Cumplimiento completo |
| LOPD-GDD (España) | Total — operación en España | Cumplimiento completo |
| ePrivacy Directive | Grabaciones, cookies | Cumplimiento completo |
| NIS2 (EU 2022/2555) | Si Saxun es operador esencial | Análisis requerido |
| ISO 27001 | Marco de seguridad | Alineado (no certificado en MVP) |

---

## 2. MANEJO DE PII (Datos Personales)

### 2.1 Taxonomía de PII en este sistema

| Dato | Clasificación | Tratamiento |
|---|---|---|
| Número de teléfono | PII directa | Hash SHA-256 inmediatamente |
| Nombre del cliente | PII directa | Solo en memoria de sesión, no persistir |
| DNI / NIE | PII sensible | Nunca almacenar; solo validar en memoria |
| Número de pedido | PII indirecta | Almacenar solo con hash de sesión |
| Dirección | PII directa | No solicitar; si se da, no persistir |
| Email | PII directa | Solo si cliente da explícitamente |
| Grabación de voz | PII biométrica | No grabar por defecto (ver sección 2.2) |
| Transcripción STT | PII derivada | Redactar antes de logs |

### 2.2 Política de grabación de llamadas

```
POR DEFECTO: NO grabar audio de la llamada.

Excepciones (requieren consentimiento explícito):
• Formación y mejora del servicio: aviso al inicio de llamada
  "Esta llamada puede ser grabada para mejorar nuestro servicio.
   Si no desea que sea grabada, pulse el 9."
• Si cliente pulsa 9: flag NO_RECORD en sesión → no grabar

Retención si se graba:
• Audio: máximo 30 días → borrado automático
• Transcripción redactada: máximo 90 días
• Metadatos de llamada (duración, fecha, cola): 12 meses (obligación legal)
```

### 2.3 Redacción automática de PII en logs

```python
import re

PII_PATTERNS = {
    "phone_es":    r'\b[6789]\d{8}\b',
    "dni_nie":     r'\b[XYZ]?\d{7,8}[A-Z]\b',
    "credit_card": r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b',
    "email":       r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
    "iban":        r'\bES\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}[\s]?\d{4}\b',
}

def redact_pii(text: str) -> str:
    """Redacta PII antes de escribir en cualquier log"""
    for name, pattern in PII_PATTERNS.items():
        text = re.sub(pattern, f'[{name.upper()}_REDACTED]', text, flags=re.IGNORECASE)
    return text

# Aplicar en STT output ANTES de enviar al LLM
# Aplicar en LLM output ANTES de escribir en logs
# NUNCA aplicar al hablar con el cliente (contexto conversacional)
```

---

## 3. ARQUITECTURA DE DATOS PRIVADOS

```
┌────────────────────────────────────────────────────────────────┐
│                   FLUJO DE DATOS CON PRIVACIDAD                │
│                                                                │
│  Audio PSTN                                                    │
│     │                                                          │
│     │ (cifrado TLS 1.3 en tránsito)                           │
│     ▼                                                          │
│  STT (Deepgram EU) ──→ Texto crudo                            │
│                              │                                 │
│                    ┌─────────▼──────────┐                      │
│                    │  PII Redactor      │ ← PRIMER filtro      │
│                    │  (en memoria,      │                      │
│                    │  no persiste)      │                      │
│                    └─────────┬──────────┘                      │
│                              │ texto redactado                 │
│                              ▼                                 │
│                    LLM (Anthropic EU) + RAG                    │
│                              │                                 │
│                    ┌─────────▼──────────┐                      │
│                    │  Output Guardrail  │ ← SEGUNDO filtro     │
│                    │  + PII check       │                      │
│                    └─────────┬──────────┘                      │
│                              │                                 │
│               ┌──────────────┼──────────────┐                  │
│               ▼              ▼              ▼                  │
│           TTS audio    Logs cifrados   CRM (solo si           │
│          (al cliente)  (sin PII)       hay handoff)           │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. CIFRADO Y ALMACENAMIENTO

### 4.1 En tránsito
- Todo tráfico: TLS 1.3
- WebSockets (audio): WSS
- Conexiones a APIs externas: TLS 1.3 con certificate pinning

### 4.2 En reposo
- RDS PostgreSQL: cifrado AES-256 (AWS KMS)
- S3 (logs/docs): SSE-S3 o SSE-KMS
- Redis: cifrado en reposo (ElastiCache encrypted)
- Backups: cifrados, región EU únicamente
- Vector DB (pgvector en RDS): incluido en cifrado de RDS

### 4.3 Gestión de claves (KMS)
```
Jerarquía de claves:
- Master Key (AWS KMS CMK): rotación anual automática
- Data Encryption Keys: derivadas de CMK, rotación mensual
- API Keys externas: AWS Secrets Manager (no en código ni .env)
- Acceso a claves: solo roles IAM autorizados, MFA obligatorio
```

---

## 5. CONTROL DE ACCESO A DOCUMENTOS RAG

```python
# Modelo de access control para documentos
class DocumentSensitivity(Enum):
    PUBLIC     = "public"       # visible a cualquier consulta
    INTERNAL   = "internal"     # solo consultas autenticadas (agentes)
    RESTRICTED = "restricted"   # solo roles específicos (DPO, Legal)
    CONFIDENTIAL = "confidential" # no disponible en RAG automático

# Reglas de acceso en retrieval
def filter_by_access_level(chunks: list[Chunk], session: Session) -> list[Chunk]:
    allowed_sensitivity = {
        "anonymous_caller": [DocumentSensitivity.PUBLIC],
        "authenticated_caller": [DocumentSensitivity.PUBLIC, DocumentSensitivity.INTERNAL],
        "agent": [DocumentSensitivity.PUBLIC, DocumentSensitivity.INTERNAL],
        "supervisor": [DocumentSensitivity.PUBLIC, DocumentSensitivity.INTERNAL,
                       DocumentSensitivity.RESTRICTED],
    }
    allowed = allowed_sensitivity.get(session.role, [DocumentSensitivity.PUBLIC])
    return [c for c in chunks if c.metadata["sensitivity"] in allowed]
```

**Principio**: el cliente (llamada anónima) solo accede a documentos `PUBLIC`. Documentos internos de precios especiales, contratos VIP, o procedimientos internos tienen `INTERNAL` o superior.

---

## 6. CONSENTIMIENTO (GDPR Art. 6 y 7)

### 6.1 Base legal para el procesamiento

| Procesamiento | Base legal GDPR |
|---|---|
| Atender la llamada | Art. 6.1.b — necesario para contrato/servicio |
| Logs de metadatos de llamada | Art. 6.1.f — interés legítimo (seguridad, calidad) |
| Grabación de audio | Art. 6.1.a — consentimiento explícito |
| Creación de ticket/reclamación | Art. 6.1.b — necesario para contrato |
| Análisis y mejora del servicio | Art. 6.1.a — consentimiento explícito |

### 6.2 Consentimiento para grabación (IVR)

```
Script al inicio (si Saxun decide grabar para mejora):
"Bienvenido a Saxun. Esta llamada puede ser grabada con fines de
 mejora del servicio. Si no desea que sea grabada, pulse el 9
 en cualquier momento."

Si pulsa 9:
• Flag NO_RECORD en sesión
• Confirmación verbal: "De acuerdo, esta llamada no será grabada."
• Continuar atención normal
```

### 6.3 Derechos del interesado (GDPR Art. 15-22)

```
Si el cliente solicita:
• Acceso a sus datos → Derivar a DPO: "Le paso con nuestro
  equipo de protección de datos para gestionar su solicitud."
• Eliminación → Misma derivación
• Portabilidad → Misma derivación
• Oposición al tratamiento → Misma derivación

NUNCA intentar gestionar solicitudes GDPR con el asistente IA.
```

---

## 7. AUDIT TRAIL

```python
# Estructura de log de auditoría (sin PII)
AUDIT_LOG = {
    "event_id": "evt_20260303_143022_xyz",
    "session_id": "sess_xyz789",       # pseudonimizado
    "caller_hash": "sha256:...",       # no reversible
    "timestamp_utc": "2026-03-03T14:30:22Z",
    "event_type": "rag_query",         # rag_query | handoff | error | consent
    "rag_docs_accessed": [             # qué documentos se consultaron
        "catalogo-2026-v2_chunk_12",
        "garantia-v1_chunk_3"
    ],
    "llm_model_used": "claude-sonnet-4-6",
    "response_confidence": 0.92,
    "action_taken": "respond",         # respond | handoff | no_evidence
    "handoff_reason": null,
    "duration_ms": 1240,
    "error": null
}

# Retención: 12 meses (obligación legal)
# Almacenamiento: S3 cifrado, acceso solo auditores
# Formato: NDJSON comprimido (gzip)
```

---

## 8. GESTIÓN DE INCIDENTES DE SEGURIDAD

```
PROTOCOLO DE RESPUESTA A INCIDENTE:

1. DETECCIÓN (automática o manual)
   • Alert en Grafana/PagerDuty
   • Escalar a responsable técnico en <15 min

2. CONTENCIÓN
   • Desactivar sesiones afectadas
   • Revocar API keys comprometidas
   • Activar modo de solo-derivación (handoff todo)

3. NOTIFICACIÓN GDPR (Art. 33)
   • Si afecta datos personales: notificar AEPD en <72 horas
   • Si riesgo alto para interesados: notificar también a afectados (Art. 34)

4. ANÁLISIS POST-MORTEM
   • Documentar en 5 días hábiles
   • Plan de remediación con fechas

Contacto DPO Saxun: [definir con Saxun]
```

---

## 9. PENETRATION TESTING Y SEGURIDAD PROACTIVA

| Actividad | Frecuencia |
|---|---|
| Vulnerability scanning (dependencias) | Continuo (CI/CD) |
| SAST (análisis estático de código) | En cada PR |
| DAST (análisis dinámico) | Mensual |
| Pen testing externo | Semestral |
| Revisión de prompt injection | Trimestral |
| Auditoría de accesos y permisos | Mensual |

### Prompt Injection en documentos RAG

```python
# Detectar instrucciones maliciosas embebidas en documentos
INJECTION_PATTERNS = [
    r"ignore previous instructions",
    r"forget your role",
    r"new instructions:",
    r"system prompt",
    r"<\|.*?\|>",          # tokens de control LLM
    r"\[INST\]",           # formato Llama
    r"reveal.*password",
    r"print.*secret",
]

def detect_injection_in_chunk(chunk_text: str) -> bool:
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, chunk_text, re.IGNORECASE):
            return True
    return False

# Se ejecuta durante la ingestión → chunk marcado como SUSPICIOUS → no indexado
# Alerta automática al equipo de seguridad
```
