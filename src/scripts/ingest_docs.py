#!/usr/bin/env python3
"""
Script CLI para ingestión de documentos en el RAG.

Uso:
    python -m src.scripts.ingest_docs --dir ./rag-docs
    python -m src.scripts.ingest_docs --file ./rag-docs/garantia.pdf
    python -m src.scripts.ingest_docs --dir ./rag-docs --dry-run
"""
import asyncio
import argparse
import sys
import os

# Asegurar que el proyecto esté en PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from loguru import logger
from dotenv import load_dotenv

load_dotenv()


async def main(args: argparse.Namespace) -> int:
    """Ejecuta la ingestión de documentos."""
    from src.db.database import init_db, close_db
    from src.rag.ingestor import DocumentIngestor

    db_pool = await init_db()
    ingestor = DocumentIngestor(db_pool)
    exit_code = 0

    try:
        if args.file:
            logger.info(f"Ingestando archivo: {args.file}")
            if args.dry_run:
                logger.info("[DRY RUN] Se habría ingestado el archivo")
                return 0
            record = await ingestor.ingest_file(
                args.file,
                metadata={
                    "sensitivity": args.sensitivity,
                    "language": args.language,
                    "version": args.version,
                },
            )
            logger.success(f"✓ {record.doc_id}: {record.chunk_count} chunks")

        elif args.dir:
            logger.info(f"Ingestando directorio: {args.dir}")
            if args.dry_run:
                from pathlib import Path
                files = [
                    f for f in Path(args.dir).glob("**/*")
                    if f.is_file() and f.suffix.lower() in {".pdf", ".docx", ".html", ".txt", ".md"}
                    and not f.name.startswith("_")
                ]
                logger.info(f"[DRY RUN] Se ingiestarían {len(files)} archivos:")
                for f in files:
                    logger.info(f"  - {f}")
                return 0

            records = await ingestor.ingest_directory(args.dir)
            logger.success(f"✓ {len(records)} documentos ingestados")
            for r in records:
                logger.info(f"  - {r.doc_id}: {r.chunk_count} chunks ({r.language})")

        else:
            logger.error("Especifica --file o --dir")
            exit_code = 1

    except Exception as e:
        logger.error(f"Error en ingestión: {e}")
        exit_code = 1
    finally:
        await close_db()

    return exit_code


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingestión de documentos en el RAG de Saxun"
    )
    parser.add_argument("--file", "-f", help="Ruta a un archivo específico")
    parser.add_argument("--dir", "-d", help="Ruta al directorio de documentos")
    parser.add_argument(
        "--sensitivity",
        choices=["public", "internal", "restricted"],
        default="public",
        help="Nivel de sensibilidad del documento",
    )
    parser.add_argument("--language", "-l", default="es", help="Idioma (es/ca/en)")
    parser.add_argument("--version", "-v", default="1.0", help="Versión del documento")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simula la ingestión sin modificar la base de datos",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    exit_code = asyncio.run(main(args))
    sys.exit(exit_code)
