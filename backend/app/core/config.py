from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://recoverai:recoverai@localhost:5432/recoverai"
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
