# Saxun Voice Assistant — Stack Recomendado
> Versión 1.0 | Fecha: 2026-03-03

---

## STACK PRINCIPAL RECOMENDADO

```
┌─────────────────┬────────────────────────┬────────────────────────────────────┐
│ CAPA            │ TECNOLOGÍA PRINCIPAL    │ ALTERNATIVAS                       │
├─────────────────┼────────────────────────┼────────────────────────────────────┤
│ Telefonía       │ Twilio                 │ Vonage, Telnyx, Asterisk           │
│ IVR             │ Twilio Studio          │ custom SIP + RTPEngine             │
│ STT             │ Deepgram Nova-3        │ Google STT, Azure Speech, Whisper  │
│ Orquestador     │ FastAPI + Python 3.12  │ Node.js + Express                  │
│ LLM             │ Claude Sonnet 4.6      │ GPT-4o, Gemini 1.5 Pro             │
│ RAG Framework   │ LangChain / LlamaIndex │ Haystack, custom                   │
│ Embeddings      │ text-embedding-3-large │ Cohere embed-v3, jina-v3           │
│ Vector DB       │ Pinecone (managed)     │ Weaviate, pgvector, Qdrant         │
│ TTS             │ ElevenLabs             │ Azure Neural TTS, Google WaveNet   │
│ Observabilidad  │ Langfuse + Grafana     │ LangSmith, Datadog                 │
│ CRM             │ Zendesk                │ Salesforce, HubSpot, custom        │
│ Infraestructura │ AWS (ECS Fargate)      │ GCP Cloud Run, Azure ACI           │
│ Cache           │ Redis                  │ Memcached                          │
│ Cola mensajes   │ Redis Streams          │ SQS, RabbitMQ                      │
│ DB principal    │ PostgreSQL (RDS)       │ MySQL, MongoDB                     │
└─────────────────┴────────────────────────┴────────────────────────────────────┘
```

---

## ANÁLISIS DETALLADO POR CATEGORÍA

### TELEFONÍA

#### Twilio (RECOMENDADO)
```
Pros:
  ✓ API madura y documentada
  ✓ Media Streams WebSocket (audio bidireccional en tiempo real)
  ✓ SIP trunking + PSTN global
  ✓ Studio para IVR visual
  ✓ Pay-as-you-go, sin coste de infraestructura SIP propia
  ✓ Integración nativa con herramientas de voz IA

Contras:
  ✗ Coste por minuto (~0.013 USD/min inbound)
  ✗ Vendor lock-in moderado
  ✗ Datos de audio pasan por servidores Twilio (Europa disponible)

Coste estimado (1000 llamadas/mes, 5 min promedio):
  ~€80-120/mes solo telefonía
```

#### Vonage / Telnyx (Alternativa)
```
Pros:
  ✓ Precios más bajos (~30% menos que Twilio)
  ✓ Telnyx: más control técnico, SIP DIY
  ✓ APIs similares

Contras:
  ✗ Ecosistema más pequeño
  ✗ Soporte menos robusto
  ✗ Menor madurez para IA voice

Recomendación: usar si el volumen justifica optimización de coste en fase 2
```

#### Asterisk / FreePBX (On-premise)
```
Pros:
  ✓ Control total sobre datos de audio
  ✓ Sin coste por minuto (solo infraestructura)
  ✓ GDPR más sencillo (datos en premises)

Contras:
  ✗ Alta complejidad operativa
  ✗ Requiere equipo especializado en VoIP
  ✗ Escalado manual

Recomendación: solo si Saxun tiene requisitos de soberanía de datos estrictos
```

---

### STT (Speech-to-Text)

#### Deepgram Nova-3 (RECOMENDADO)
```
Pros:
  ✓ Latencia más baja del mercado (<200ms streaming)
  ✓ Soporte español excelente (incluyendo acentos ibéricos)
  ✓ VAD integrado y barge-in detection
  ✓ Endpointing configurable
  ✓ PII redaction nativa (números, emails)
  ✓ Precio razonable (~$0.0043/min)

Contras:
  ✗ Menos conocido que Google/Azure
  ✗ Catalán/valenciano limitado (en progreso)

Coste estimado (1000 llamadas × 5 min): ~€22/mes
```

#### Azure Speech Services (Enterprise Fallback)
```
Pros:
  ✓ SLA garantizado (99.9%)
  ✓ Cumplimiento GDPR certificado (Azure EU regions)
  ✓ Soporte catalán disponible
  ✓ Custom Speech para vocabulario Saxun

Contras:
  ✗ Latencia mayor (~400-600ms)
  ✗ Precio más alto (~$0.016/min)

Recomendación: usar como fallback o para catalán/valenciano
```

---

### LLM

#### Claude Sonnet 4.6 (RECOMENDADO)
```
Pros:
  ✓ Mejor razonamiento para RAG con citación
  ✓ Sigue instrucciones complejas (políticas, guardrails)
  ✓ Contexto largo (200k tokens)
  ✓ Structured output nativo
  ✓ Bajo rate de alucinación en tareas factuales
  ✓ API Anthropic: región EU disponible

Contras:
  ✗ Coste: ~$3/M input tokens, $15/M output tokens
  ✗ No hay fine-tuning disponible (aún)

Coste estimado por llamada (1000 tokens avg):
  ~€0.004-0.015 por llamada según complejidad
```

#### Claude Haiku 4.5 (Para respuestas simples)
```
Uso: intenciones simples (horarios, dirección), confirmaciones
Ventaja: 10x más barato, ~50% menos latencia
Coste: ~$0.001/M input tokens
```

#### GPT-4o (Alternativa)
```
Pros:
  ✓ Excelente calidad, multimodal
  ✓ Amplia documentación y comunidad

Contras:
  ✗ OpenAI: datos pueden procesarse fuera de EU (Azure OpenAI soluciona esto)
  ✗ Fine-tuning más caro
  ✗ Menor adherencia a instrucciones restrictivas vs Claude

Recomendación: alternativa viable, usar Azure OpenAI para GDPR
```

---

### VECTOR DATABASE

#### Pinecone (RECOMENDADO)
```
Pros:
  ✓ Fully managed, sin operativa de infra
  ✓ Escalado automático
  ✓ Latencia < 50ms en búsquedas
  ✓ Namespaces para multitenancy
  ✓ Filtrado por metadata eficiente

Contras:
  ✗ Vendor lock-in
  ✗ Datos en US por defecto (EU disponible en plan Enterprise)
  ✗ Coste: ~$70/mes para 1M vectores

GDPR: usar región Europe (Pinecone EU) o alternativa europea
```

#### pgvector (Alternativa Self-Hosted)
```
Pros:
  ✓ En tu propia PostgreSQL (RDS Europa)
  ✓ Control total de datos
  ✓ Sin coste adicional si ya tienes RDS
  ✓ Transactions ACID junto con metadatos

Contras:
  ✗ Búsqueda aprox. (HNSW) menos optimizada que Pinecone
  ✗ Requiere tunning para alta escala (>1M vectores)
  ✗ Búsqueda híbrida más compleja de implementar

Recomendación: IDEAL para MVP (coste 0 extra) + cumplimiento GDPR sencillo
```

#### Qdrant (Alternativa Self-Hosted/Cloud EU)
```
Pros:
  ✓ Cloud EU disponible (Alemania)
  ✓ Búsqueda híbrida nativa (dense + sparse)
  ✓ Código abierto, sin vendor lock-in
  ✓ Payload filtering avanzado

Contras:
  ✗ Menos maduro que Pinecone
  ✗ Requiere algo de operativa

Recomendación: mejor alternativa open-source para producción
```

---

### TTS (Text-to-Speech)

#### ElevenLabs (RECOMENDADO)
```
Pros:
  ✓ Voz más natural del mercado (difícil distinguir de humano)
  ✓ Latencia streaming: ~300-500ms primera sílaba
  ✓ Clonación de voz (branded voice de Saxun)
  ✓ SSML y estilos emocionales
  ✓ Español natural excelente

Contras:
  ✗ Precio: ~$0.30/1000 chars (~€15-30/mes para 1000 llamadas)
  ✗ Servidores mayoritariamente US (EU en Enterprise)
  ✗ API relativamente nueva

Plan: Enterprise para datos EU + SLA
```

#### Azure Neural TTS (Enterprise Fallback)
```
Pros:
  ✓ SLA 99.9%, región EU
  ✓ Voces neurales de alta calidad (es-ES-AlvaroNeural, etc.)
  ✓ Precio predecible (~$16/1M chars)
  ✓ GDPR certificado

Contras:
  ✗ Ligeramente menos natural que ElevenLabs
  ✗ Voz branded requiere proceso especial (Custom Neural Voice)

Recomendación: usar como fallback automático si ElevenLabs falla
```

---

## ARQUITECTURA DE INFRAESTRUCTURA

```
┌─────────────────────────────────────────────────────────┐
│                   AWS (región EU-West-1)                 │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │                ECS Fargate Cluster                │   │
│  │                                                  │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │   │
│  │  │ Orquestador │  │ RAG Ingest  │  │ Monitor  │ │   │
│  │  │ (3 replicas)│  │ (batch job) │  │ Workers  │ │   │
│  │  └─────────────┘  └─────────────┘  └──────────┘ │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐  │
│  │ RDS PG   │  │ Redis    │  │ S3 (docs + audio logs)│  │
│  │ (pgvect.)│  │ Cache    │  │ con cifrado SSE-S3     │  │
│  └──────────┘  └──────────┘  └───────────────────────┘  │
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │  API Gateway → ALB → ECS (auto-scaling)         │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Sizing para MVP (hasta 5000 llamadas/mes)

| Recurso | Especificación | Coste/mes estimado |
|---|---|---|
| ECS Fargate (orquestador) | 2 vCPU, 4GB RAM × 3 | ~€120 |
| RDS PostgreSQL + pgvector | db.t3.medium | ~€60 |
| Redis (ElastiCache) | cache.t3.micro | ~€20 |
| S3 (logs, docs) | 50 GB | ~€5 |
| Twilio (telefonía) | 5000 min/mes | ~€80 |
| Deepgram (STT) | 5000 min/mes | ~€22 |
| Claude API (LLM) | ~2M tokens/mes | ~€40 |
| ElevenLabs (TTS) | ~10M chars/mes | ~€30 |
| **TOTAL infraestructura** | | **~€377/mes** |

*Langfuse (self-hosted en ECS): €0 adicional*
*Grafana OSS: €0 adicional*

---

## DECISIONES DE DISEÑO CLAVE

| Decisión | Elección | Justificación |
|---|---|---|
| Sync vs Async LLM | Streaming | Reduce latencia percibida (TTS empieza antes) |
| Modelo routing | Haiku→Sonnet | Haiku para intent, Sonnet para respuesta |
| Estado de sesión | Redis TTL 30min | Sin base de datos para estado efímero |
| Audio logs | No guardar por defecto | GDPR: solo metadatos. Opt-in explícito |
| Vector DB MVP | pgvector | GDPR + coste 0 + sencillez |
| Embeddings | text-embedding-3-large | Mejor calidad ES, multilingual |
