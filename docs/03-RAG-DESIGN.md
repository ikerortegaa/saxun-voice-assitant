# Saxun Voice Assistant — Diseño del Pipeline RAG
> Versión 1.0 | Fecha: 2026-03-03

---

## VISIÓN GENERAL

```
┌─────────────────────────────────────────────────────────────────┐
│                    RAG PIPELINE — SAXUN                         │
│                                                                 │
│  INGESTIÓN                ÍNDICE                   RETRIEVAL   │
│                                                                 │
│  rag-docs/           →   Chunking         →   Query            │
│  (PDF/DOCX/HTML)         Embedding            Embedding        │
│  CMS / SharePoint        Metadata             Hybrid Search    │
│                          Vector DB            Re-ranking       │
│                          (pgvector)           Guardrail        │
│                                                                 │
│                                    →   LLM Response            │
│                                        + Citations             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 1. INGESTIÓN DE DOCUMENTOS

### 1.1 Estructura de carpeta rag-docs/

```
rag-docs/
├── productos/
│   ├── catalogo-2026.pdf
│   ├── fichas-tecnicas/
│   └── precios-vigentes.pdf          ← fecha en metadata
├── politicas/
│   ├── garantia.pdf
│   ├── devolucion.pdf
│   └── privacidad-gdpr.pdf
├── soporte/
│   ├── faq-general.pdf
│   ├── procedimientos-tecnicos.pdf
│   └── escalados.pdf
├── comercial/
│   ├── contacto-delegados.pdf
│   └── condiciones-contrato.pdf
└── _meta/
    ├── document_registry.json         ← control de versiones
    └── freshness_policy.yaml          ← reglas de caducidad
```

### 1.2 Formatos soportados y parsers

| Formato | Parser | Notas |
|---|---|---|
| PDF | PyMuPDF (fitz) | Preserva estructura, extrae tablas |
| DOCX | python-docx | Tablas → markdown |
| HTML | BeautifulSoup4 | Limpieza de tags, preserva headings |
| XLSX | pandas + openpyxl | Tablas → texto estructurado |
| TXT/MD | directo | |

**Regla**: si OCR es necesario (PDFs escaneados) → usar Tesseract o Azure AI Document Intelligence.

### 1.3 Proceso de ingestión

```python
# Pseudocódigo del pipeline de ingestión
def ingest_document(file_path: str, metadata: dict) -> list[Chunk]:

    # 1. Parsing
    raw_text = parse_document(file_path)

    # 2. Limpieza
    clean_text = clean_text(raw_text)
    # - eliminar cabeceras/pies de página repetidos
    # - normalizar espacios, encoding UTF-8
    # - detectar y descartar páginas en blanco

    # 3. Detección de idioma
    lang = detect_language(clean_text)  # es/ca/en

    # 4. Chunking semántico (ver sección 1.4)
    chunks = semantic_chunker(clean_text, max_tokens=512, overlap=50)

    # 5. Enriquecimiento de metadata
    for chunk in chunks:
        chunk.metadata = {
            "doc_id": generate_stable_id(file_path),
            "chunk_id": f"{doc_id}_{chunk.index}",
            "source": file_path,
            "title": extract_title(raw_text),
            "section": chunk.section_heading,
            "language": lang,
            "version": metadata.get("version", "1.0"),
            "effective_date": metadata.get("effective_date"),
            "expiry_date": metadata.get("expiry_date"),         # freshness
            "sensitivity": metadata.get("sensitivity", "public"), # access control
            "last_ingested": datetime.utcnow().isoformat(),
        }

    # 6. Embedding
    embeddings = embed_chunks(chunks)  # text-embedding-3-large

    # 7. Deduplicación
    chunks = deduplicate(chunks, threshold=0.97)  # cosine sim

    # 8. Upsert en Vector DB
    vector_db.upsert(chunks, embeddings)

    return chunks
```

### 1.4 Estrategia de Chunking

**Principio**: chunk semántico > chunk por tokens fijos.

```
Estrategia:
1. Dividir primero por headings/secciones del documento
2. Dentro de cada sección: chunks de ~400-512 tokens
3. Overlap de 50 tokens entre chunks consecutivos
4. Chunk mínimo: 50 tokens (descartar fragmentos vacíos)
5. Chunk máximo: 600 tokens (si excede, subdividir por párrafos)

Caso especial — FAQs:
- Cada par pregunta+respuesta = 1 chunk atómico
- No separar pregunta de respuesta

Caso especial — Tablas:
- Tabla entera = 1 chunk (no fragmentar)
- Si tabla > 600 tokens → convertir a texto estructurado
  ("El precio de X es Y euros, el de Z es W euros...")

Caso especial — Listas de pasos:
- Lista completa = 1 chunk (contexto necesario)
```

### 1.5 Versionado y deduplicación

```yaml
# document_registry.json — estructura
{
  "doc_id": "catalogo-2026-v2",
  "file_hash": "sha256:abc123...",
  "version": "2.0",
  "previous_version": "1.0",
  "status": "active",        # active | superseded | expired
  "effective_date": "2026-01-01",
  "expiry_date": "2026-12-31",
  "ingested_at": "2026-01-05T10:00:00Z",
  "chunk_count": 47,
  "language": "es"
}
```

**Proceso de actualización de documento:**
1. Calcular hash del nuevo documento
2. Comparar con hash almacenado → si igual, skip
3. Si diferente → marcar versión antigua como `superseded`
4. Ingestar nueva versión (nuevos `chunk_id`)
5. Versión antigua permanece en DB con flag `superseded` durante 7 días (rollback)
6. Purgar versión antigua tras 7 días

---

## 2. RETRIEVAL PIPELINE

### 2.1 Hybrid Search (Dense + Sparse)

```
Query del usuario → Query Embedding (dense)
                 → BM25 / keyword search (sparse)
                 →
                     Fusión con RRF (Reciprocal Rank Fusion)
                 →
                     Top-20 candidatos
                 →
                     Re-ranking (Cross-Encoder)
                 →
                     Top-5 chunks → LLM
```

**¿Por qué Hybrid?**
- Dense: captura semántica (sinónimos, paráfrasis)
- Sparse: captura exactitud léxica (nombres propios, números de referencia, códigos de producto)
- Ambos necesarios para un contact center real

### 2.2 Implementación de Hybrid Search con pgvector

```sql
-- Búsqueda semántica (pgvector)
SELECT chunk_id, content, metadata,
       1 - (embedding <=> query_embedding) as semantic_score
FROM chunks
WHERE status = 'active'
  AND (expiry_date IS NULL OR expiry_date > NOW())
  AND language IN ('es', 'ca', 'en')
ORDER BY semantic_score DESC
LIMIT 20;

-- Búsqueda léxica (tsvector)
SELECT chunk_id, content, metadata,
       ts_rank(to_tsvector('spanish', content),
               plainto_tsquery('spanish', :query)) as lexical_score
FROM chunks
WHERE to_tsvector('spanish', content) @@ plainto_tsquery('spanish', :query)
  AND status = 'active'
LIMIT 20;

-- Fusión RRF en Python
def reciprocal_rank_fusion(semantic_results, lexical_results, k=60):
    scores = defaultdict(float)
    for rank, (chunk_id, _) in enumerate(semantic_results):
        scores[chunk_id] += 1 / (k + rank + 1)
    for rank, (chunk_id, _) in enumerate(lexical_results):
        scores[chunk_id] += 1 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

### 2.3 Re-ranking

```python
# Cross-encoder re-ranking (ms-marco-MiniLM-L-6-v2)
from sentence_transformers import CrossEncoder

reranker = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')

def rerank(query: str, candidates: list[Chunk], top_k: int = 5) -> list[Chunk]:
    pairs = [(query, chunk.content) for chunk in candidates]
    scores = reranker.predict(pairs)
    ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
    return [chunk for chunk, score in ranked[:top_k]]
```

### 2.4 Citación Interna

El LLM recibe los chunks con sus IDs y debe citarlos en el output estructurado:

```json
{
  "response_text": "La garantía de los productos Saxun es de dos años desde la fecha de compra.",
  "confidence": 0.92,
  "action": "respond",
  "citations": [
    {
      "chunk_id": "garantia-v1_chunk_3",
      "doc_title": "Política de Garantía 2026",
      "section": "Duración de la garantía",
      "relevance_score": 0.94
    }
  ],
  "evidence_found": true,
  "language": "es"
}
```

**Importante**: Las citaciones NO se verbalizan al cliente. Son para:
- Audit trail
- Debugging
- Dashboard de calidad
- Detección de documentos poco utilizados

---

## 3. GUARDRAILS Y ANTI-ALUCINACIÓN

### 3.1 Política de respuesta basada en confianza

```
┌─────────────────────────────────────────────────────────────┐
│              ÁRBOL DE DECISIÓN DE CONFIANZA                 │
│                                                             │
│  ¿evidence_found = true?                                    │
│       YES →  confidence ≥ 0.85 → RESPOND (normal)          │
│              confidence 0.65-0.84 → RESPOND + confirmar    │
│              confidence < 0.65  → NO RESPOND + derivar     │
│                                                             │
│       NO  →  SIEMPRE → NO RESPOND + derivar                 │
│                                                             │
│  ¿La respuesta contiene PII del cliente? → BLOQUEAR         │
│  ¿La pregunta toca área sensible (legal, médica)? → DERIVAR │
│  ¿El cliente lleva >2 turnos sin resolución? → DERIVAR      │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 System Prompt Anti-Alucinación (fragmento)

```
REGLAS ABSOLUTAS:
1. SOLO responde con información explícitamente presente en los DOCUMENTOS aportados.
2. Si la información NO está en los documentos, di exactamente:
   "No tengo esa información en este momento. ¿Le paso con uno de nuestros especialistas?"
3. NUNCA inventes precios, fechas, nombres o especificaciones técnicas.
4. Si tienes información parcial, indícalo: "Tengo información sobre X, pero no sobre Y."
5. NUNCA digas "como IA" o "como asistente virtual".
6. Respuestas de voz: máximo 2 frases cortas (≤25 palabras cada una).
7. Siempre confirma antes de dar instrucciones de más de 3 pasos.

DOCUMENTOS DE REFERENCIA:
{rag_context}

HISTORIAL DE CONVERSACIÓN:
{conversation_history}

CONSULTA DEL CLIENTE:
{user_query}
```

### 3.3 Post-processing Guardrails

```python
def apply_guardrails(llm_response: dict) -> dict:
    """Guardrails aplicados DESPUÉS del LLM, ANTES de TTS"""

    # 1. Detectar si el LLM alucinó (heurístico)
    if contains_invented_data(llm_response["response_text"]):
        return fallback_response("derivation")

    # 2. PII en respuesta (no debería existir, pero verificar)
    if detect_pii(llm_response["response_text"]):
        return redact_pii(llm_response)

    # 3. Verificar que las citas existen en la DB
    for citation in llm_response["citations"]:
        if not chunk_exists(citation["chunk_id"]):
            llm_response["confidence"] *= 0.5  # penalizar

    # 4. Verificar freshness de documentos citados
    for citation in llm_response["citations"]:
        if is_document_expired(citation["chunk_id"]):
            return stale_document_response()

    # 5. Verificar longitud para voz
    if token_count(llm_response["response_text"]) > 100:
        llm_response["response_text"] = truncate_for_voice(
            llm_response["response_text"]
        )

    return llm_response
```

### 3.4 Detección de falta de evidencia

```python
EVIDENCE_ABSENCE_INDICATORS = [
    # Patrones que indican que el LLM está alucinando sin evidencia
    r"según mi conocimiento",
    r"generalmente",
    r"en la mayoría de casos",
    r"normalmente",
    r"suele ser",
    # Si ningún chunk_id en citations → no_evidence
]

def check_evidence_quality(response: dict) -> bool:
    if not response.get("citations"):
        return False
    if response.get("confidence", 0) < 0.65:
        return False
    for indicator in EVIDENCE_ABSENCE_INDICATORS:
        if re.search(indicator, response["response_text"], re.IGNORECASE):
            return False
    return True
```

---

## 4. CONTROL DE FRESHNESS

```yaml
# freshness_policy.yaml
policies:
  - doc_pattern: "precios-*.pdf"
    max_age_days: 30       # precios: revisar mensualmente
    alert_at_days: 25      # alertar 5 días antes de expirar

  - doc_pattern: "catalogo-*.pdf"
    max_age_days: 90
    alert_at_days: 80

  - doc_pattern: "politica-garantia*.pdf"
    max_age_days: 365
    alert_at_days: 340

  - doc_pattern: "faq-*.pdf"
    max_age_days: 60
    alert_at_days: 50

  default:
    max_age_days: 180
    alert_at_days: 160
```

**Proceso automático:**
1. Job diario verifica fechas de todos los documentos
2. Si documento próximo a expirar → alerta a responsable Saxun (email/Slack)
3. Si documento expirado → se marca `expired` en DB, no se devuelve en búsquedas
4. Si se intenta responder con solo documentos expirados → derivación automática

---

## 5. MULTILENGUAJE EN RAG

```
Estrategia:
1. Los documentos se ingresan con metadata "language: es/ca/en"
2. Los embeddings son multilingüales (text-embedding-3-large soporta ES/CA/EN)
3. En retrieval, se filtra por idioma detectado en la query
4. Si no hay docs en el idioma solicitado → buscar en español + notificar
5. Sistema de traducción de chunks (futuro): MT para ampliar cobertura
```

### Detección de idioma

```python
from langdetect import detect
from lingua import Language, LanguageDetectorBuilder

# Detector específico para ES/CA/EN
detector = LanguageDetectorBuilder.from_languages(
    Language.SPANISH, Language.CATALAN, Language.ENGLISH
).build()

def detect_language(text: str) -> str:
    lang = detector.detect_language_of(text)
    return {
        Language.SPANISH: "es",
        Language.CATALAN: "ca",
        Language.ENGLISH: "en"
    }.get(lang, "es")  # default español
```
