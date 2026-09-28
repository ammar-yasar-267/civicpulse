"""Application configuration, read from the environment only.

Nothing here has a hardcoded credential and nothing reads a file from the repo:
secrets arrive from .env (dev), a Kubernetes Secret (cluster) or GitHub Secrets (CI).
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["llm", "ollama", "rules", "simulated"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # --- database ---
    postgres_user: str = "civicpulse"
    postgres_password: str = "civicpulse"
    postgres_db: str = "civicpulse"
    postgres_host: str = "database"
    postgres_port: int = 5432

    # --- cache ---
    redis_host: str = "cache"
    redis_port: int = 6379

    # --- triage ---
    triage_provider: ProviderName = "rules"
    triage_timeout_seconds: float = 10.0
    triage_cache_ttl_seconds: int = 86_400
    stats_cache_ttl_seconds: int = 30

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.1-8b-instant"

    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2:1b"

    # Deterministic fake used by CI. Non-zero injects failures on every Nth call.
    simulated_failure_every: int = 0
    simulated_malformed_every: int = 0

    # --- rate limiting ---
    rate_limit_requests: int = 10
    rate_limit_window_seconds: int = 60

    # --- app ---
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173"
    max_page_size: int = Field(default=100, frozen=True)

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
