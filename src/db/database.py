"""
Gestión de conexiones a base de datos (PostgreSQL + pgvector) y Redis.
Pool de conexiones async con asyncpg.
"""
import asyncpg
import redis.asyncio as aioredis
from loguru import logger

from src.config import get_settings

_db_pool: asyncpg.Pool | None = None
_redis_client: aioredis.Redis | None = None


async def get_db_pool() -> asyncpg.Pool:
    """Devuelve el pool de conexiones PostgreSQL (singleton)."""
    global _db_pool
    if _db_pool is None:
        await init_db()
    return _db_pool


async def get_redis() -> aioredis.Redis:
    """Devuelve el cliente Redis (singleton)."""
    global _redis_client
    if _redis_client is None:
        await init_redis()
    return _redis_client


async def init_db() -> asyncpg.Pool:
    """Inicializa el pool de conexiones PostgreSQL con soporte pgvector."""
    global _db_pool
    settings = get_settings()

    # asyncpg no acepta el prefijo sqlalchemy — limpiar URL
    db_url = settings.database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )

    async def init_connection(conn: asyncpg.Connection) -> None:
        """Configurar cada conexión: codec pgvector."""
        from pgvector.asyncpg import register_vector
        await register_vector(conn)

    _db_pool = await asyncpg.create_pool(
        dsn=db_url,
        min_size=2,
        max_size=settings.database_pool_size,
        max_inactive_connection_lifetime=300,
        init=init_connection,
    )
    logger.info(f"PostgreSQL pool creado (max_size={settings.database_pool_size})")
    return _db_pool


async def init_redis() -> aioredis.Redis:
    """Inicializa el cliente Redis."""
    global _redis_client
    settings = get_settings()
    _redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
    )
    # Verificar conexión
    await _redis_client.ping()
    logger.info("Redis conectado")
    return _redis_client


async def close_db() -> None:
    """Cierra conexiones al finalizar la app."""
    global _db_pool, _redis_client
    if _db_pool:
        await _db_pool.close()
        _db_pool = None
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None
    logger.info("Conexiones de base de datos cerradas")
