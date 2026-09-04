from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://recoverai:recoverai@localhost:5432/recoverai"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3_driver(cls, value: str) -> str:
        # Managed Postgres providers (e.g. Railway) inject a plain
        # "postgresql://" URL -- this project only installs psycopg v3
        # (see backend/requirements.txt), so SQLAlchemy needs the explicit
        # "+psycopg" driver segment or it falls back to the (uninstalled)
        # psycopg2 dialect and fails to connect.
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value
    razorpay_mode: str = "mock"
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    llm_api_key: str = ""
    llm_model: str = "gemini-3.6-flash"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3100"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
