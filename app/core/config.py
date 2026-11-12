"""Typed, validated settings loaded once from the environment.

WHY: config read via os.environ at call sites fails *late* (first request in prod).
A pydantic-settings model fails *at import*, so a typo in .env never reaches runtime.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "FastAPI Mastery"
    debug: bool = True

    database_url: str = "sqlite+aiosqlite:///./app.db"

    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    openai_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-4o-mini"
    chroma_dir: str = "./chroma_data"

    @property
    def ai_live(self) -> bool:
        """True when a real LLM provider is configured; otherwise AI endpoints mock."""
        return bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    """lru_cache => one Settings instance per process, and a drop-in Depends() provider."""
    return Settings()
