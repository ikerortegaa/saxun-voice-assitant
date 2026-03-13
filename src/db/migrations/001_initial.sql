-- ============================================================
-- Saxun Voice Assistant — Migración inicial
-- PostgreSQL 15+ con extensión pgvector
-- ============================================================

-- Habilitar pgvector
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- Para búsqueda fuzzy opcional

-- ── Registro de documentos ─────────────────────────────────
CREATE TABLE IF NOT EXISTS document_registry (
    doc_id          VARCHAR(255) PRIMARY KEY,
    file_path       VARCHAR(1000) NOT NULL,
    file_hash       VARCHAR(64)  NOT NULL,
    title           VARCHAR(500),
    version         VARCHAR(50)  DEFAULT '1.0',
    status          VARCHAR(20)  DEFAULT 'active'
                    CHECK (status IN ('active', 'superseded', 'expired')),
    language        VARCHAR(5)   DEFAULT 'es',
    sensitivity     VARCHAR(20)  DEFAULT 'public'
                    CHECK (sensitivity IN ('public', 'internal', 'restricted', 'confidential')),
    effective_date  DATE,
    expiry_date     DATE,
    chunk_count     INTEGER      DEFAULT 0,
    ingested_at     TIMESTAMPTZ  DEFAULT NOW(),
    metadata        JSONB        DEFAULT '{}',

    CONSTRAINT doc_status_check CHECK (status IN ('active', 'superseded', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_doc_registry_status
    ON document_registry (status);

CREATE INDEX IF NOT EXISTS idx_doc_registry_expiry
    ON document_registry (expiry_date)
    WHERE expiry_date IS NOT NULL;

-- ── Chunks con embeddings ──────────────────────────────────
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id        VARCHAR(255) PRIMARY KEY,
    doc_id          VARCHAR(255) NOT NULL
                    REFERENCES document_registry(doc_id) ON DELETE CASCADE,
    content         TEXT         NOT NULL,
    section         VARCHAR(500) DEFAULT '',
    language        VARCHAR(5)   DEFAULT 'es',
    sensitivity     VARCHAR(20)  DEFAULT 'public',
    status          VARCHAR(20)  DEFAULT 'active'
                    CHECK (status IN ('active', 'superseded', 'expired')),
    chunk_index     INTEGER      DEFAULT 0,
    embedding       VECTOR(1536),           -- text-embedding-3-small dimensions
    metadata        JSONB        DEFAULT '{}',
    created_at      TIMESTAMPTZ  DEFAULT NOW(),

    -- Para full-text search
    content_tsv     TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('spanish', content)
    ) STORED
);

-- Índice HNSW para búsqueda de vecinos aproximada (pgvector)
-- Parámetros: m=16, ef_construction=64 (balance velocidad/calidad)
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Índice GIN para full-text search
CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv
    ON chunks USING gin (content_tsv);

-- Índices de filtrado
CREATE INDEX IF NOT EXISTS idx_chunks_doc_status
    ON chunks (doc_id, status);

CREATE INDEX IF NOT EXISTS idx_chunks_language_status
    ON chunks (language, status);

CREATE INDEX IF NOT EXISTS idx_chunks_sensitivity
    ON chunks (sensitivity, status);

-- ── Sesiones (opcional — para persistencia fuera de Redis) ──
-- En MVP las sesiones viven en Redis. Esta tabla es para auditoría.
CREATE TABLE IF NOT EXISTS session_audit (
    session_id          VARCHAR(255) PRIMARY KEY,
    call_sid            VARCHAR(255),
    caller_hash         VARCHAR(64)  NOT NULL,
    language            VARCHAR(5)   DEFAULT 'es',
    started_at          TIMESTAMPTZ  DEFAULT NOW(),
    ended_at            TIMESTAMPTZ,
    turn_count          INTEGER      DEFAULT 0,
    handoff_triggered   BOOLEAN      DEFAULT FALSE,
    containment         BOOLEAN      DEFAULT TRUE,
    duration_seconds    FLOAT,
    metadata            JSONB        DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_session_audit_started
    ON session_audit (started_at);

CREATE INDEX IF NOT EXISTS idx_session_audit_caller
    ON session_audit (caller_hash);

-- ── Logs de auditoría ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_logs (
    id              BIGSERIAL    PRIMARY KEY,
    event_id        VARCHAR(100) NOT NULL UNIQUE,
    event_type      VARCHAR(50)  NOT NULL,
    session_id      VARCHAR(255),
    caller_hash     VARCHAR(64),
    timestamp_utc   TIMESTAMPTZ  DEFAULT NOW(),
    data            JSONB        DEFAULT '{}',

    CONSTRAINT audit_no_pii CHECK (
        -- Verificar que no haya campos con PII obvia
        NOT (data::text ~ '\b[6789]\d{8}\b')  -- no teléfonos ES
    )
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_session
    ON audit_logs (session_id);

CREATE INDEX IF NOT EXISTS idx_audit_logs_event_type
    ON audit_logs (event_type, timestamp_utc);

CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp
    ON audit_logs (timestamp_utc);

-- Retención automática de logs (90 días para operación)
-- Ejecutar como job periódico:
-- DELETE FROM audit_logs WHERE timestamp_utc < NOW() - INTERVAL '90 days';

-- ── Vista para dashboard de calidad ───────────────────────
CREATE OR REPLACE VIEW v_daily_metrics AS
SELECT
    DATE(timestamp_utc)             AS metric_date,
    COUNT(*)                        AS total_events,
    COUNT(*) FILTER (
        WHERE event_type = 'call_start'
    )                               AS total_calls,
    COUNT(*) FILTER (
        WHERE event_type = 'handoff_triggered'
    )                               AS total_handoffs,
    ROUND(AVG(
        CASE WHEN event_type = 'rag_query'
        THEN (data->>'latency_ms')::float END
    )::numeric, 1)                  AS avg_rag_latency_ms,
    ROUND(AVG(
        CASE WHEN event_type = 'rag_query'
        THEN (data->>'top_score')::float END
    )::numeric, 3)                  AS avg_rag_score
FROM audit_logs
GROUP BY DATE(timestamp_utc)
ORDER BY metric_date DESC;

-- ── Función de freshness check ────────────────────────────
CREATE OR REPLACE FUNCTION check_document_freshness()
RETURNS TABLE (
    doc_id      VARCHAR(255),
    title       VARCHAR(500),
    expiry_date DATE,
    days_until_expiry INTEGER,
    status      VARCHAR(20)
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        dr.doc_id,
        dr.title,
        dr.expiry_date,
        (dr.expiry_date - CURRENT_DATE)::INTEGER AS days_until_expiry,
        dr.status
    FROM document_registry dr
    WHERE dr.status = 'active'
      AND dr.expiry_date IS NOT NULL
      AND dr.expiry_date <= CURRENT_DATE + INTERVAL '30 days'
    ORDER BY dr.expiry_date ASC;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Datos de ejemplo para testing (eliminar en producción)
-- ============================================================
-- INSERT INTO document_registry (doc_id, file_path, file_hash, title, status)
-- VALUES ('test-doc-001', '/test/doc.pdf', 'abc123', 'Documento de prueba', 'active');
