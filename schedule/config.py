from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    secret_key: str = ""
    algorithm: str = "HS256"
    mongodb_url: str = ""
    google_api_key: str = ""
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30
    model_config = SettingsConfigDict(env_file=".env")


@lru_cache
def get_settings():
    return Settings()


settings = get_settings()
