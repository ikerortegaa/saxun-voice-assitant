"""
Configuración central del proyecto Saxun Voice Assistant.
Todos los parámetros se cargan desde variables de entorno / .env
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── OpenAI ────────────────────────────────────────────────
    openai_api_key: str
    openai_llm_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_embedding_dimensions: int = 1536

    # ── Twilio ────────────────────────────────────────────────
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str

    # ── Deepgram ──────────────────────────────────────────────
    deepgram_api_key: str
    deepgram_model: str = "nova-2"
    deepgram_language: str = "es"

    # ── TTS (proveedor: "openai" | "azure" | "elevenlabs") ───────
    tts_provider: str = "openai"
    openai_tts_model: str = "tts-1"          # "tts-1" | "tts-1-hd"
    openai_tts_speed: float = 0.9

    # ── Azure Speech (opcional — solo si tts_provider=azure) ─────
    azure_speech_key: str = ""
    azure_speech_region: str = "westeurope"  # región del recurso Azure

    # ── ElevenLabs (opcional — solo si tts_provider=elevenlabs) ──
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = ""
    elevenlabs_model_id: str = "eleven_multilingual_v2"

    # ── Base de datos ─────────────────────────────────────────
    database_url: str
    database_pool_size: int = 10
    database_max_overflow: int = 20

    # ── Redis ─────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_session_ttl: int = 1800  # 30 minutos

    # ── Langfuse ──────────────────────────────────────────────
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # ── App ───────────────────────────────────────────────────
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_base_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    # ── RAG ───────────────────────────────────────────────────
    rag_docs_path: str = "./rag-docs"
    rag_top_k: int = 3
    rag_confidence_threshold: float = 0.65
    rag_high_confidence_threshold: float = 0.85
    rag_chunk_size: int = 450
    rag_chunk_overlap: int = 50

    # ── Seguridad ─────────────────────────────────────────────
    secret_key: str = "change-me-in-production"

    # ── Handoff colas ─────────────────────────────────────────
    handoff_default_queue: str = ""
    handoff_queue_technical: str = ""
    handoff_queue_commercial: str = ""
    handoff_queue_complaints: str = ""

    # ── CRM ───────────────────────────────────────────────────
    zendesk_subdomain: str = ""
    zendesk_email: str = ""
    zendesk_api_token: str = ""

    # ── Modo emergencia ───────────────────────────────────────
    emergency_mode: bool = False

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def zendesk_enabled(self) -> bool:
        return bool(self.zendesk_subdomain and self.zendesk_api_token)

    @property
    def elevenlabs_enabled(self) -> bool:
        return bool(self.elevenlabs_api_key and self.elevenlabs_voice_id)


@lru_cache
def get_settings() -> Settings:
    return Settings()
