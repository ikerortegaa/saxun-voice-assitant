"""
Rutas de administración — Gestión de documentos RAG, métricas y salud del sistema.
Acceso restringido: solo uso interno/operacional.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header
from fastapi.responses import JSONResponse
from loguru import logger

from src.config import get_settings
from src.db.database import get_db_pool
from src.rag.ingestor import DocumentIngestor
from src.rag.retriever import HybridRetriever


router = APIRouter()


def verify_admin_token(x_admin_token: str = Header(...)):
    """Verificación básica de token de admin (en producción usar OAuth2/JWT)."""
    settings = get_settings()
    if x_admin_token != settings.secret_key:
        raise HTTPException(status_code=403, detail="Token de administrador inválido")
    return True


# ── Gestión de documentos ─────────────────────────────────────────────────────

@router.post("/documents/ingest")
async def ingest_document(
    file: UploadFile = File(...),
    sensitivity: str = "public",
    language: str = "es",
    version: str = "1.0",
    _: bool = Depends(verify_admin_token),
):
    """
    Ingesta un documento en el RAG.
    Sube el archivo, lo parsea, genera embeddings y lo indexa.
    """
    if not file.filename:
        raise HTTPException(400, "Nombre de archivo requerido")

    allowed_extensions = {".pdf", ".docx", ".html", ".htm", ".txt", ".md"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(400, f"Formato no soportado: {ext}. Use: {allowed_extensions}")

    # Guardar temporalmente
    tmp_path = f"/tmp/saxun_ingest_{file.filename}"
    try:
        content = await file.read()
        with open(tmp_path, "wb") as f:
            f.write(content)

        db_pool = await get_db_pool()
        ingestor = DocumentIngestor(db_pool)
        record = await ingestor.ingest_file(
            tmp_path,
            metadata={
                "sensitivity": sensitivity,
                "language": language,
                "version": version,
                "original_filename": file.filename,
            },
        )

        return {
            "status": "success",
            "doc_id": record.doc_id,
            "title": record.title,
            "chunk_count": record.chunk_count,
            "language": record.language,
        }
    except Exception as e:
        logger.error(f"Error ingestando {file.filename}: {e}")
        raise HTTPException(500, f"Error de ingestión: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


@router.post("/documents/ingest-directory")
async def ingest_directory(
    directory: str = "./rag-docs",
    _: bool = Depends(verify_admin_token),
):
    """Ingesta todos los documentos de un directorio."""
    db_pool = await get_db_pool()
    ingestor = DocumentIngestor(db_pool)
    records = await ingestor.ingest_directory(directory)
    return {
        "status": "success",
        "ingested_count": len(records),
        "documents": [
            {"doc_id": r.doc_id, "title": r.title, "chunks": r.chunk_count}
            for r in records
        ],
    }


@router.get("/documents")
async def list_documents(
    status: Optional[str] = "active",
    _: bool = Depends(verify_admin_token),
):
    """Lista todos los documentos del registro."""
    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT doc_id, title, version, status, language, sensitivity,
                   chunk_count, effective_date, expiry_date, ingested_at
            FROM document_registry
            WHERE ($1::text IS NULL OR status = $1)
            ORDER BY ingested_at DESC
            """,
            status,
        )
    return {"documents": [dict(row) for row in rows]}


@router.delete("/documents/{doc_id}")
async def expire_document(
    doc_id: str,
    _: bool = Depends(verify_admin_token),
):
    """Marca un documento como expirado (no se elimina físicamente)."""
    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE document_registry SET status = 'expired' WHERE doc_id = $1",
            doc_id,
        )
        await conn.execute(
            "UPDATE chunks SET status = 'expired' WHERE doc_id = $1",
            doc_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(404, f"Documento no encontrado: {doc_id}")
    logger.info(f"Documento expirado: {doc_id}")
    return {"status": "success", "doc_id": doc_id, "new_status": "expired"}


@router.post("/documents/{doc_id}/rollback")
async def rollback_document(
    doc_id: str,
    target_version: str,
    _: bool = Depends(verify_admin_token),
):
    """Rollback a versión anterior de un documento."""
    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            # Supersede versión actual
            await conn.execute(
                "UPDATE document_registry SET status = 'superseded' WHERE doc_id = $1 AND status = 'active'",
                doc_id,
            )
            # Reactivar versión target
            await conn.execute(
                "UPDATE document_registry SET status = 'active' WHERE doc_id = $1 AND version = $2",
                doc_id, target_version,
            )
            await conn.execute(
                "UPDATE chunks SET status = 'active' WHERE doc_id = $1",
                doc_id,
            )
    logger.info(f"Rollback: {doc_id} → v{target_version}")
    return {"status": "success", "doc_id": doc_id, "rolled_back_to": target_version}


# ── Búsqueda / testing del RAG ────────────────────────────────────────────────

@router.post("/rag/search")
async def rag_search(
    query: str,
    top_k: int = 5,
    language: Optional[str] = None,
    _: bool = Depends(verify_admin_token),
):
    """Permite probar el retrieval del RAG directamente (para verificación)."""
    db_pool = await get_db_pool()
    retriever = HybridRetriever(db_pool)
    result = await retriever.retrieve(query=query, top_k=top_k, language=language)
    return {
        "query": query,
        "method": result.method,
        "latency_ms": result.latency_ms,
        "chunks": [
            {
                "chunk_id": c.chunk_id,
                "doc_id": c.doc_id,
                "section": c.section,
                "score": round(c.score, 4),
                "content_preview": c.content[:200] + "..." if len(c.content) > 200 else c.content,
            }
            for c in result.chunks
        ],
    }


# ── Sistema y métricas ────────────────────────────────────────────────────────

@router.get("/health")
async def admin_health(_: bool = Depends(verify_admin_token)):
    """Health check detallado del sistema."""
    from src.db.database import _db_pool, _redis_client
    health = {
        "status": "ok",
        "database": "unknown",
        "redis": "unknown",
        "emergency_mode": get_settings().emergency_mode,
    }
    try:
        if _db_pool:
            await _db_pool.execute("SELECT 1")
            health["database"] = "ok"
    except Exception as e:
        health["database"] = f"error: {e}"
        health["status"] = "degraded"

    try:
        if _redis_client:
            await _redis_client.ping()
            health["redis"] = "ok"
    except Exception as e:
        health["redis"] = f"error: {e}"
        health["status"] = "degraded"

    return health


@router.post("/emergency-mode")
async def set_emergency_mode(
    enabled: bool,
    _: bool = Depends(verify_admin_token),
):
    """
    Activa/desactiva el modo emergencia (solo derivación).
    En producción: modificar la variable de entorno y reiniciar.
    """
    import os
    os.environ["EMERGENCY_MODE"] = str(enabled).lower()
    # Limpiar cache de settings
    get_settings.cache_clear()
    logger.warning(f"Modo emergencia: {'ACTIVADO' if enabled else 'DESACTIVADO'}")
    return {"status": "success", "emergency_mode": enabled}


@router.get("/documents/freshness")
async def check_freshness(_: bool = Depends(verify_admin_token)):
    """Lista documentos próximos a expirar o ya expirados."""
    db_pool = await get_db_pool()
    async with db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM check_document_freshness()")
    return {
        "documents_expiring_soon": [dict(row) for row in rows],
        "count": len(rows),
    }
