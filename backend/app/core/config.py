"""Application settings (goals.md §5 + Environment Variables).

Loaded from backend/.env or the process environment. MONGODB_URI is optional
at this stage — no database is wired until Step 2, so the app boots without it.
"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Inference (Groq, OpenAI-compatible SDK)
    GROQ_API_KEY: str = ""
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    GROQ_MODEL: str = "openai/gpt-oss-120b"          # primary (goals.md §5)
    GROQ_FALLBACK_MODEL: str = "openai/gpt-oss-20b"  # enrichment-only fallback

    # Database (wired in Step 2)
    MONGODB_URI: str = ""
    MONGODB_DB_NAME: str = "ria_v2"

    # HTTP
    CORS_ORIGINS: str = "http://localhost:3000"
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
