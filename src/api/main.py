"""
FastAPI — Aplicación principal del Saxun Voice Assistant.
Configura middleware, lifespan, routers y métricas.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from prometheus_client import make_asgi_app

from src.config import get_settings
from src.db.database import init_db, init_redis, close_db
from src.api.routes import voice_router, admin_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Ciclo de vida de la aplicación: startup → yield → shutdown."""
    settings = get_settings()
    logger.info(f"Iniciando Saxun Voice Assistant ({settings.app_env})")

    # Inicializar conexiones
    db_pool = await init_db()
    redis = await init_redis()

    # Almacenar en app.state para acceso desde routes
    app.state.db_pool = db_pool
    app.state.redis = redis

    # Inicializar Langfuse si está configurado
    if settings.langfuse_enabled:
        try:
            from langfuse import Langfuse
            app.state.langfuse = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            logger.info("Langfuse inicializado")
        except Exception as e:
            logger.warning(f"Langfuse no disponible: {e}")

    logger.info("✓ Saxun Voice Assistant listo")
    yield

    # Shutdown limpio
    logger.info("Apagando Saxun Voice Assistant...")
    await close_db()
    logger.info("Shutdown completado")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Saxun Voice Assistant API",
        version="1.0.0",
        description="Asistente de voz IA para atención al cliente de Saxun",
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # CORS (solo en desarrollo)
    if not settings.is_production:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Métricas Prometheus en /metrics
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)

    # Routers
    app.include_router(voice_router, prefix="/api/v1/voice", tags=["voice"])
    app.include_router(admin_router, prefix="/api/v1/admin", tags=["admin"])

    @app.get("/health")
    async def health_check():
        return {"status": "ok", "service": "saxun-voice-assistant"}

    @app.get("/")
    async def root():
        return {"message": "Saxun Voice Assistant — AITIK Solutions"}

    return app


# Entry point
app = create_app()
